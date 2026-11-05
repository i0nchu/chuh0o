import os
import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "assets" / "manifest.json").exists():
        return checkout
    return Path(sys.prefix) / "share" / "chuh0o"


def data_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "chuh0o"
