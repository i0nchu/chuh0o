"""On-demand GitHub release checks and unsigned portable-ZIP updates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from PySide6.QtCore import (
    QIODevice,
    QObject,
    QRunnable,
    QSaveFile,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from chuh0o import __version__
from chuh0o.paths import resource_root

REPOSITORY = "i0nchu/chuh0o"
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_UNPACKED = 768 * 1024 * 1024
MAX_METADATA = 1024 * 1024
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class UpdateError(ValueError):
    pass


def version_key(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"[vV]?(\d{1,9})\.(\d{1,9})\.(\d{1,9})", value)
    if not match:
        raise UpdateError("版本格式必須是 v1.2.3")
    return tuple(int(part) for part in match.groups())


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    digest: str | None


def select_release(payload: dict, current: str, repository: str = REPOSITORY) -> Release | None:
    if (
        not isinstance(payload, dict)
        or payload.get("draft") is not False
        or payload.get("prerelease") is not False
    ):
        raise UpdateError("不是可用的正式版本")
    tag = payload.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateError("缺少版本號碼")
    latest = version_key(tag)
    if latest <= version_key(current):
        return None
    version = ".".join(map(str, latest))
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("缺少下載檔案")
    expected_name = f"chuh0o-v{version}-windows-x64.zip"
    matches = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and asset.get("name") == expected_name
        and asset.get("state") == "uploaded"
    ]
    if len(matches) != 1:
        raise UpdateError("尚無可下載的 Windows 版本")
    asset = matches[0]
    url = asset.get("browser_download_url", "")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or not parsed.path.lower().startswith(f"/{repository.lower()}/releases/download/")
    ):
        raise UpdateError("下載位置不是指定的 GitHub Release")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE:
        raise UpdateError("下載檔案大小不正確")
    digest = asset.get("digest")
    if digest is not None:
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise UpdateError("檔案雜湊格式不正確")
        digest = digest.split(":", 1)[1].lower()
    return Release(version, url, size, digest)


def unpack_release(archive: Path, job: Path, cancel: threading.Event | None = None) -> Path:
    """Validate every ZIP member before writing anything; never extract links or traversal paths."""
    output = (job / "unpacked").resolve()
    if output.exists():
        raise UpdateError("更新暫存目錄已存在")
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if not entries or len(entries) > 5000 or sum(v.file_size for v in entries) > MAX_UNPACKED:
            raise UpdateError("更新包過大或內容不正確")
        names = set()
        for entry in entries:
            name = entry.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or not path.parts
                or any(
                    part in (".", "..")
                    or ":" in part
                    or part != part.rstrip(" .")
                    or part.split(".", 1)[0].upper() in RESERVED_NAMES
                    for part in path.parts
                )
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise UpdateError("更新包含不安全的路徑")
            key = str(path).lower()
            if key in names:
                raise UpdateError("更新包含重複檔案")
            names.add(key)
            if not (output / str(path)).resolve().is_relative_to(output):
                raise UpdateError("更新包路徑超出暫存目錄")
        output.mkdir(parents=True)
        for entry in entries:
            if cancel is not None and cancel.is_set():
                raise UpdateError("更新已取消")
            target = output / entry.filename.replace("\\", "/")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, 1024 * 1024)
    candidates = [path for path in (output, output / "chuh0o") if (path / "chuh0o.exe").is_file()]
    if len(candidates) != 1:
        raise UpdateError("更新包不是桌寵的 Windows 發行檔")
    app = candidates[0]
    required = (
        "_internal/assets/manifest.json",
        "_internal/PySide6/QtCore.pyd",
        "_internal/PySide6/QtGui.pyd",
        "_internal/PySide6/QtWidgets.pyd",
    )
    if not all((app / name).is_file() for name in required):
        raise UpdateError("更新包缺少執行環境或素材")
    with (app / "chuh0o.exe").open("rb") as executable:
        if executable.read(2) != b"MZ":
            raise UpdateError("更新包的執行檔不正確")
    return app


def installed_app_directory() -> Path | None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if executable.name.lower() != "chuh0o.exe":
        return None
    return executable.parent


def validate_install_target(app: Path, directory: Path) -> None:
    if app.is_symlink() or app.is_junction():
        raise UpdateError("無法更新連結資料夾")
    target, data = app.resolve(), directory.resolve()
    if data == target or data.is_relative_to(target) or (target / ".git").exists():
        raise UpdateError("程式與設定資料夾必須分開，開發原始碼不能自動替換")
    if (
        not (target / "chuh0o.exe").is_file()
        or not (target / "_internal/assets/manifest.json").is_file()
    ):
        raise UpdateError("找不到已安裝的桌寵")
    with tempfile.NamedTemporaryFile(prefix=".chuh0o-update-", dir=target.parent):
        pass


def launch_update_helper(plan: Path) -> None:
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.Popen(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(plan.parent / "apply_update.ps1"),
            "-PlanPath",
            str(plan),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=plan.parent,
    )


def write_ready_marker(path: Path, directory: Path) -> None:
    path = path.resolve()
    if not path.is_relative_to((directory / "updates").resolve()):
        raise UpdateError("更新確認路徑不正確")
    path.write_text(json.dumps({"version": __version__, "pid": os.getpid()}), encoding="utf-8")


class PrepareSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class PrepareJob(QRunnable):
    def __init__(self, archive: Path, job: Path, cancel: threading.Event):
        super().__init__()
        self.archive, self.job, self.cancel = archive, job, cancel
        self.signals = PrepareSignals()

    def run(self) -> None:
        try:
            staged = unpack_release(self.archive, self.job, self.cancel)
            if self.cancel.is_set():
                raise UpdateError("更新已取消")
            self.signals.done.emit(staged)
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
            unpacked = (self.job / "unpacked").resolve()
            if unpacked.is_relative_to(self.job.resolve()) and unpacked.is_dir():
                shutil.rmtree(unpacked, ignore_errors=True)
            self.signals.failed.emit(str(error))


class UpdateManager(QObject):
    changed = Signal(str, str)
    ready = Signal(object)

    def __init__(
        self,
        directory: Path,
        parent: QObject | None = None,
        network: QNetworkAccessManager | None = None,
        install_directory: Path | None = None,
        current_version: str = __version__,
    ):
        super().__init__(parent)
        self.directory = directory.resolve()
        self.current_version = current_version
        self.install_directory = install_directory
        self.network = network or QNetworkAccessManager(self)
        self.network.setTransferTimeout(15000)
        self.state = "ready"
        self.message = ""
        self.release: Release | None = None
        self.reply: QNetworkReply | None = None
        self._file: QSaveFile | None = None
        self._generation = 0
        self._job: Path | None = None
        self._received = 0
        self._hasher = hashlib.sha256()
        self._cancel = threading.Event()
        self._worker: PrepareJob | None = None
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._timed_out)

    def set_state(self, state: str, message: str = "") -> None:
        self.state, self.message = state, message
        self.changed.emit(state, message)

    def reset_menu(self) -> None:
        if self.state in ("downloading", "preparing", "installing"):
            return
        self._abort_request()
        self.release = None
        self.set_state("ready")

    def activate(self) -> None:
        if self.state == "available":
            self.download()
        elif self.state in ("ready", "error", "update_error", "no_release", "development"):
            self.check()

    def _request(self, url: str, timeout: int) -> QNetworkReply:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", f"chuh0o/{self.current_version}".encode("ascii"))
        request.setRawHeader(
            b"Accept",
            b"application/vnd.github+json"
            if "api.github.com" in url
            else b"application/octet-stream",
        )
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        self.reply = self.network.get(request)
        self._deadline.start(timeout)
        return self.reply

    def check(self) -> None:
        self._abort_request()
        self.release = None
        self.set_state("checking")
        generation = self._generation
        reply = self._request(f"https://api.github.com/repos/{REPOSITORY}/releases/latest", 20000)
        reply.readyRead.connect(lambda: self._guard_metadata(reply))
        reply.finished.connect(lambda: self._checked(reply, generation))

    def _guard_metadata(self, reply: QNetworkReply) -> None:
        if reply is self.reply and reply.bytesAvailable() > MAX_METADATA:
            self.fail("版本回應過大")

    def _checked(self, reply: QNetworkReply, generation: int) -> None:
        if generation != self._generation or reply is not self.reply:
            reply.deleteLater()
            return
        self._deadline.stop()
        self.reply = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status == 404:
                self.set_state("no_release", "GitHub 尚無可用的正式版本")
            elif reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                self.set_state("error", "無法連線 GitHub，請稍後重試")
            else:
                body = bytes(reply.readAll())
                if len(body) > MAX_METADATA:
                    raise UpdateError("版本回應過大")
                self.release = select_release(json.loads(body), self.current_version)
                self.set_state("available" if self.release else "current")
        except (ValueError, TypeError, UnicodeError) as error:
            self.set_state("error", str(error))
        finally:
            reply.deleteLater()

    def download(self) -> None:
        if self.release is None:
            return
        if self.install_directory is None:
            self.set_state("development", "開發預覽不替換原始碼，請使用發布版進行更新")
            return
        self._abort_request()
        self._job = self.directory / "updates" / uuid.uuid4().hex
        try:
            self._job.mkdir(parents=True)
            self._file = QSaveFile(str(self._job / "package.zip"))
            if not self._file.open(QIODevice.OpenModeFlag.WriteOnly):
                raise UpdateError("無法建立更新暫存檔")
        except (OSError, ValueError) as error:
            self.fail(str(error))
            return
        self._received = 0
        self._hasher = hashlib.sha256()
        self._cancel.clear()
        self.set_state("downloading")
        generation = self._generation
        reply = self._request(self.release.url, 300000)
        reply.readyRead.connect(lambda: self._download_chunk(reply, generation))
        reply.finished.connect(lambda: self._downloaded(reply, generation))

    def _download_chunk(self, reply: QNetworkReply, generation: int) -> None:
        if generation != self._generation or reply is not self.reply or self._file is None:
            return
        block = bytes(reply.readAll())
        self._received += len(block)
        if self.release is None or self._received > min(self.release.size, MAX_ARCHIVE):
            self.fail("下載檔案大小超出預期")
            return
        if self._file.write(block) != len(block):
            self.fail("無法儲存下載檔案")
            return
        self._hasher.update(block)
        self.set_state("downloading", str(min(100, self._received * 100 // self.release.size)))

    def _downloaded(self, reply: QNetworkReply, generation: int) -> None:
        if generation != self._generation or reply is not self.reply:
            reply.deleteLater()
            return
        self._download_chunk(reply, generation)
        if generation != self._generation:
            reply.deleteLater()
            return
        self._deadline.stop()
        self.reply = None
        try:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if reply.error() != QNetworkReply.NetworkError.NoError or status != 200:
                raise UpdateError("下載失敗，請重試")
            if self.release is None or self._received != self.release.size:
                raise UpdateError("下載不完整")
            if self.release.digest and self._hasher.hexdigest() != self.release.digest:
                raise UpdateError("下載檔案的 SHA-256 不符合")
            if self._file is None or not self._file.commit():
                raise UpdateError("無法完成下載檔案")
            self._file = None
            self.set_state("preparing")
            self._worker = PrepareJob(self._job / "package.zip", self._job, self._cancel)
            self._worker.signals.done.connect(self._prepared)
            self._worker.signals.failed.connect(self.fail)
            QThreadPool.globalInstance().start(self._worker)
        except (OSError, ValueError) as error:
            self.fail(str(error))
        finally:
            reply.deleteLater()

    @Slot(object)
    def _prepared(self, staged: Path) -> None:
        if self._cancel.is_set() or self.release is None or self._job is None:
            return
        try:
            validate_install_target(self.install_directory, self.directory)
            helper = resource_root() / "resources" / "apply_update.ps1"
            shutil.copyfile(helper, self._job / "apply_update.ps1")
            plan = {
                "app_dir": str(self.install_directory),
                "staged_dir": str(staged),
                "data_dir": str(self.directory),
                "parent_pid": os.getpid(),
                "new_version": self.release.version,
            }
            plan_path = self._job / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            self.set_state("installing")
            self.ready.emit(plan_path)
        except (OSError, ValueError) as error:
            self.fail(str(error))

    def _abort_request(self) -> None:
        self._generation += 1
        self._deadline.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        if self._file is not None:
            self._file.cancelWriting()
            self._file = None

    @Slot(str)
    def fail(self, message: str) -> None:
        failed_state = (
            "update_error" if self.state in ("downloading", "preparing", "installing") else "error"
        )
        self._abort_request()
        self.set_state(failed_state, message)

    def _timed_out(self) -> None:
        self.fail("連線逾時，請重試")

    def close(self) -> None:
        self._cancel.set()
        self._abort_request()
