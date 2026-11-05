# Build with: python -m PyInstaller --noconfirm chuh0o.spec
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'src' / 'main.py')],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=[(str(root / 'assets'), 'assets'), (str(root / 'config.json'), '.'),
           (str(root / 'resources' / 'apply_update.ps1'), 'resources')],
    hiddenimports=['win32timezone'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtQml', 'PySide6.QtQuick', 'tkinter', 'pytest'],
    noarchive=False,
)
# Windows 11 provides the system ICU API. A tool's PATH may contain Poppler's
# incompatible icuuc.dll; bundling it shadows the Windows DLL and breaks QtCore.
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith('icu')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='chuh0o',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, icon=str(root / 'assets' / 'bunny.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='chuh0o')
