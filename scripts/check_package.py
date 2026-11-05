"""Start the standalone build outside the checkout CWD and verify single-instance behavior."""

import json
import os
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "qa-output"
output.mkdir(exist_ok=True)
data = output / "packaged-data"
executable = root / "dist" / "chuh0o" / "chuh0o.exe"
environment = {
    key: value
    for key, value in os.environ.items()
    if key not in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "QT_QPA_PLATFORM")
}
environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
command = [str(executable), "--data-dir", str(data)]
child = subprocess.Popen([*command, "--quit-after", "30"], cwd=output, env=environment)
try:
    time.sleep(3)
    running = child.poll() is None
    started = time.monotonic()
    duplicate = subprocess.run(
        [*command, "--quit-after", "15"], cwd=output, env=environment, timeout=20
    )
    single_instance = duplicate.returncode == 0 and time.monotonic() - started < 8
    code = child.wait(timeout=40)
finally:
    if child.poll() is None:
        child.terminate()
        child.wait(timeout=5)
results = {
    "standalone_started": running,
    "single_instance": single_instance,
    "clean_exit": code == 0,
    "bundled_assets": all(
        (executable.parent / "_internal" / "assets" / name).exists()
        for name in ("manifest.json", "idle.png", "check.svg")
    ),
    "bundled_updater": (executable.parent / "_internal/resources/apply_update.ps1").is_file(),
    "no_validation_report": not (executable.parent / "VALIDATION.md").exists(),
}
(output / "package-smoke.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results))
raise SystemExit(0 if all(results.values()) else 1)
