import hashlib
import io
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QIODevice, QPoint, Qt, QTimer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtTest import QSignalSpy, QTest

from chuh0o.activity.modes import Activity
from chuh0o.activity.updates import (
    REPOSITORY,
    UpdateError,
    UpdateManager,
    select_release,
    unpack_release,
    validate_install_target,
    version_key,
    write_ready_marker,
)
from chuh0o.core.animator import SpriteBank
from chuh0o.core.config import ConfigStore, Settings
from chuh0o.core.controller import Controller


def bundle_bytes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("chuh0o/chuh0o.exe", b"MZnew")
        archive.writestr("chuh0o/_internal/assets/manifest.json", '{"animations": {}}')
        for module in ("QtCore", "QtGui", "QtWidgets"):
            archive.writestr(f"chuh0o/_internal/PySide6/{module}.pyd", b"runtime")
    return output.getvalue()


def payload(version="0.2.0", data=b"test", digest=True):
    name = f"chuh0o-v{version}-windows-x64.zip"
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": name,
                "state": "uploaded",
                "size": len(data),
                "digest": "sha256:" + hashlib.sha256(data).hexdigest() if digest else None,
                "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{name}",
            }
        ],
    }


def installed_fixture(tmp_path):
    app = tmp_path / "installed"
    (app / "_internal/assets").mkdir(parents=True)
    (app / "chuh0o.exe").write_bytes(b"MZold")
    (app / "_internal/assets/manifest.json").write_text("{}")
    return app


def wait_state(manager, state):
    for _ in range(200):
        if manager.state == state:
            return
        QTest.qWait(10)
    raise AssertionError(f"Expected {state}; got {manager.state}: {manager.message}")


class FakeReply(QNetworkReply):
    def __init__(self, request, status, data, delay=0, error=None, parent=None):
        super().__init__(parent)
        self.data = data
        self.done = False
        self.error_value = error
        self.setRequest(request)
        self.setUrl(request.url())
        self.setAttribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute, status)
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)
        QTimer.singleShot(delay, self.finish)

    def finish(self):
        if self.done:
            return
        self.done = True
        if self.error_value is not None:
            self.setError(self.error_value, "Test network error")
        self.readyRead.emit()
        self.setFinished(True)
        self.finished.emit()

    def bytesAvailable(self):
        return len(self.data) + super().bytesAvailable()

    def readData(self, maximum):
        data, self.data = self.data[:maximum], self.data[maximum:]
        return data

    def abort(self):
        if not self.done:
            self.done = True
            self.setError(QNetworkReply.NetworkError.OperationCanceledError, "Canceled")
            self.setFinished(True)
            self.finished.emit()


class FakeNetwork(QNetworkAccessManager):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.requests = []

    def get(self, request):
        self.requests.append(request.url().toString())
        return FakeReply(request, **self.responses.pop(0), parent=self)


def test_release_comparison_uses_numeric_versions_and_no_paid_signature():
    assert version_key("v0.10.0") > version_key("0.9.9")
    assert select_release(payload("0.1.10", digest=False), "0.1.9").digest is None
    assert select_release(payload("0.1.0"), "0.1.0") is None
    assert select_release(payload("0.1.0"), "0.2.0") is None


@pytest.mark.parametrize(
    "change",
    [
        {"draft": True},
        {"prerelease": True},
        {"tag_name": "v0.2.0-rc1"},
        {"assets": []},
        {"tag_name": "invalid"},
    ],
)
def test_nonstable_and_nondownloadable_releases_are_not_offered(change):
    data = payload()
    data.update(change)
    with pytest.raises(UpdateError):
        select_release(data, "0.1.0")


def test_release_download_must_be_https_and_from_configured_repo():
    data = payload()
    data["assets"][0]["browser_download_url"] = "https://example.com/program.zip"
    with pytest.raises(UpdateError):
        select_release(data, "0.1.0")


def test_complete_portable_bundle_is_staged_without_touching_installed_app(tmp_path):
    old = installed_fixture(tmp_path)
    job = tmp_path / "job"
    job.mkdir()
    archive = job / "package.zip"
    archive.write_bytes(bundle_bytes())
    stage = unpack_release(archive, job)
    assert (stage / "chuh0o.exe").read_bytes() == b"MZnew"
    assert (old / "chuh0o.exe").read_bytes() == b"MZold"


@pytest.mark.parametrize(
    "name", ["../escape", "C:/escape", "a/../../escape", "\\\\server\\file", "bad:stream"]
)
def test_zip_traversal_is_rejected_before_extraction(tmp_path, name):
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(name, b"bad")
    with pytest.raises(UpdateError):
        unpack_release(archive, tmp_path)
    assert not (tmp_path / "unpacked").exists()


def test_zip_symlinks_and_case_collisions_are_rejected(tmp_path):
    archive = tmp_path / "package.zip"
    entry = zipfile.ZipInfo("link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(entry, "../outside")
    with pytest.raises(UpdateError):
        unpack_release(archive, tmp_path)
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("a.dll", "one")
        package.writestr("A.dll", "two")
    with pytest.raises(UpdateError):
        unpack_release(archive, tmp_path)


def test_source_checkout_and_settings_cannot_be_replaced(tmp_path):
    old = installed_fixture(tmp_path)
    with pytest.raises(UpdateError):
        validate_install_target(old, old / "settings")
    (old / ".git").mkdir()
    with pytest.raises(UpdateError):
        validate_install_target(old, tmp_path / "data")


def test_ready_marker_is_limited_to_the_update_cache(tmp_path):
    marker = tmp_path / "updates" / "job" / "ready.json"
    marker.parent.mkdir(parents=True)
    write_ready_marker(marker, tmp_path)
    assert json.loads(marker.read_text())["version"] == "0.1.0"
    with pytest.raises(UpdateError):
        write_ready_marker(tmp_path / "config.json", tmp_path)


def test_checker_states_reset_and_development_cannot_install(app, tmp_path):
    network = FakeNetwork([{"status": 200, "data": json.dumps(payload()).encode()}])
    manager = UpdateManager(tmp_path, network=network)
    try:
        manager.activate()
        assert manager.state == "checking"
        wait_state(manager, "available")
        manager.activate()
        assert manager.state == "development" and len(network.requests) == 1
        manager.reset_menu()
        assert manager.state == "ready" and manager.release is None
    finally:
        manager.close()


@pytest.mark.parametrize("status,expected", [(404, "no_release"), (403, "error"), (200, "current")])
def test_http_results_are_not_falsely_reported_as_current(app, tmp_path, status, expected):
    network = FakeNetwork([{"status": status, "data": json.dumps(payload("0.1.0")).encode()}])
    manager = UpdateManager(tmp_path, network=network)
    try:
        manager.activate()
        wait_state(manager, expected)
        manager.reset_menu()
        assert manager.state == "ready"
    finally:
        manager.close()


def test_reopening_menu_cancels_inflight_check_and_ignores_stale_result(app, tmp_path):
    network = FakeNetwork(
        [
            {"status": 200, "data": json.dumps(payload()).encode(), "delay": 50},
            {"status": 200, "data": json.dumps(payload("0.1.0")).encode()},
        ]
    )
    manager = UpdateManager(tmp_path, network=network)
    try:
        manager.activate()
        manager.reset_menu()
        manager.activate()
        wait_state(manager, "current")
        QTest.qWait(80)
        assert manager.state == "current" and manager.release is None
    finally:
        manager.close()


def test_download_and_unpack_prepare_external_handoff_without_replacing_running_files(
    app, tmp_path
):
    data = bundle_bytes()
    old = installed_fixture(tmp_path)
    network = FakeNetwork(
        [
            {"status": 200, "data": json.dumps(payload(data=data)).encode()},
            {"status": 200, "data": data},
        ]
    )
    manager = UpdateManager(tmp_path / "data", network=network, install_directory=old)
    ready = QSignalSpy(manager.ready)
    try:
        manager.activate()
        wait_state(manager, "available")
        manager.activate()
        wait_state(manager, "installing")
        assert ready.count() == 1
        plan = json.loads(Path(ready.at(0)[0]).read_text(encoding="utf-8"))
        assert Path(plan["staged_dir"]).is_relative_to(tmp_path / "data/updates")
        assert (Path(plan["staged_dir"]) / "chuh0o.exe").read_bytes() == b"MZnew"
        assert (old / "chuh0o.exe").read_bytes() == b"MZold"
        manager.reset_menu()
        assert manager.state == "installing"
    finally:
        manager.close()


def test_corrupt_download_does_not_replace_installed_app(app, tmp_path):
    data = bundle_bytes()
    metadata = payload(data=data)
    metadata["assets"][0]["digest"] = "sha256:" + "0" * 64
    old = installed_fixture(tmp_path)
    network = FakeNetwork(
        [
            {"status": 200, "data": json.dumps(metadata).encode()},
            {"status": 200, "data": data},
        ]
    )
    manager = UpdateManager(tmp_path / "data", network=network, install_directory=old)
    ready = QSignalSpy(manager.ready)
    try:
        manager.activate()
        wait_state(manager, "available")
        manager.activate()
        wait_state(manager, "update_error")
        assert "SHA-256" in manager.message and ready.count() == 0
        assert (old / "chuh0o.exe").read_bytes() == b"MZold"
    finally:
        manager.close()


def ps_quote(path):
    return "'" + str(path).replace("'", "''") + "'"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows update helper")
@pytest.mark.parametrize("healthy,outside", [(True, False), (False, False), (True, True)])
def test_windows_helper_swaps_complete_bundle_or_rolls_back(tmp_path, healthy, outside):
    old = installed_fixture(tmp_path)
    data = tmp_path / "data with spaces"
    job = data / "updates" / ("a" * 32)
    job.mkdir(parents=True)
    archive = job / "package.zip"
    archive.write_bytes(bundle_bytes())
    staged = unpack_release(archive, job)
    if outside:
        unrelated = tmp_path / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep.txt").write_text("untouched")
        staged = unrelated
    config = data / "config.json"
    config.write_text('{"scale": 1.25}')
    plan = job / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "app_dir": str(old),
                "staged_dir": str(staged),
                "data_dir": str(data),
                "parent_pid": 2147483647,
                "new_version": "0.2.0",
            }
        ),
        encoding="utf-8",
    )
    helper = job / "apply_update.ps1"
    helper.write_bytes(
        (Path(__file__).resolve().parents[1] / "resources/apply_update.ps1").read_bytes()
    )
    harness = job / "harness.ps1"
    # Real filesystem transitions; only process launching/health are substituted.
    harness.write_text(
        f". {ps_quote(helper)}\n"
        "function Start-Pet { param($Executable, $DataDirectory, $ReadyFile); "
        "return [pscustomobject]@{ Id = 123 } }\n"
        "function Wait-PetReady { param($Process, $ReadyFile, $Version); "
        f"return ${str(healthy).lower()} }}\n"
        "function Stop-UpdatedPet { param($Process, $ExpectedExecutable) }\n"
        f"exit (Invoke-PetUpdate -PlanPath {ps_quote(plan)})\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
        ],
        capture_output=True,
        timeout=30,
    )
    success = healthy and not outside
    assert result.returncode == (0 if success else 1), result.stderr.decode(errors="replace")
    assert (old / "chuh0o.exe").read_bytes() == (b"MZnew" if success else b"MZold")
    assert config.read_text() == '{"scale": 1.25}'
    status = json.loads((job / "result.json").read_text(encoding="utf-8"))["status"]
    assert status == ("updated" if success else "failed")
    if outside:
        assert (staged / "keep.txt").read_text() == "untouched"


class MenuBackend:
    available = True

    def sample(self):
        return Activity()

    def configure_window(self, hwnd, through):
        pass


def make_menu_controller(app, tmp_path, developer=False):
    root = Path(__file__).resolve().parents[1]
    controller = Controller(
        app,
        SpriteBank(root / "assets"),
        Settings(),
        ConfigStore(tmp_path / "config.json"),
        MenuBackend(),
        development_actions=developer,
    )
    controller.apply_policy()
    return controller


def close_menu_controller(controller):
    controller.tray.menu.close()
    controller.updates.close()
    controller.render_timer.stop()
    controller.activity_timer.stop()
    controller.tray.icon.hide()
    controller.window.hide()
    controller.window.deleteLater()
    controller.tray.menu.deleteLater()
    controller.deleteLater()


def test_update_row_keeps_menu_open_shows_result_and_resets_next_open(app, tmp_path):
    controller = make_menu_controller(app, tmp_path)
    network = FakeNetwork(
        [
            {"status": 200, "data": json.dumps(payload()).encode()},
            {"status": 200, "data": json.dumps(payload("0.1.0")).encode()},
        ]
    )
    network.setParent(controller.updates)
    controller.updates.network = network
    try:
        menu, action = controller.tray.menu, controller.tray.update
        point = controller.window.mapToGlobal(QPoint(72, 100))
        controller.show_pet_menu(point)
        app.processEvents()
        assert action.text() == "檢查更新"
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
        wait_state(controller.updates, "available")
        assert menu.isVisible() and action.text() == "更新"
        menu.close()
        controller.show_pet_menu(point)
        assert action.text() == "檢查更新" and action.isEnabled()
        menu.setActiveAction(action)
        QTest.keyClick(menu, Qt.Key.Key_Return)
        wait_state(controller.updates, "current")
        assert menu.isVisible() and action.text() == "已為最新版本" and not action.isEnabled()
        menu.close()
        controller.show_pet_menu(point)
        assert action.text() == "檢查更新" and action.isEnabled()
        assert len(network.requests) == 2
    finally:
        close_menu_controller(controller)


def test_short_visibility_labels_and_source_only_developer_actions(app, tmp_path, monkeypatch):
    normal = make_menu_controller(app, tmp_path / "normal")
    developer = make_menu_controller(app, tmp_path / "developer", developer=True)
    frozen = None
    try:
        assert normal.tray.visibility.text() == "隱藏" and not normal.tray.actions
        normal.toggle_visible()
        assert normal.tray.visibility.text() == "顯示"
        assert set(developer.tray.actions) == {"wave", "lie", "jump"}
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        frozen = make_menu_controller(app, tmp_path / "frozen", developer=True)
        assert not frozen.tray.actions
    finally:
        if frozen is not None:
            close_menu_controller(frozen)
        close_menu_controller(developer)
        close_menu_controller(normal)
