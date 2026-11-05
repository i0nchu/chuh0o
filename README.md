# chuh0o · 粉紅兔兔桌寵

Windows 11 的像素兔兔桌寵，支援走路、連續跳躍、打招呼、側躺與睡眠。

![兔兔動畫](assets/preview.gif)

## 下載使用

1. 到 [Releases](https://github.com/i0nchu/chuh0o/releases/latest) 下載 `chuh0o-v0.1.0-windows-x64.zip`。
2. 完整解壓縮，執行 `chuh0o/chuh0o.exe`，不需要安裝 Python。
3. 請保留同資料夾內的 `_internal`，不要只移動 EXE。

- 左鍵點擊：打招呼；按住拖曳：移動兔兔，放手後垂直落下。
- 右鍵兔兔或系統匣圖示：隱藏、暫停、運行模式、滑鼠穿透、設定、檢查更新及退出。
- 鍵盤滑鼠閒置一分鐘後睡覺，有新輸入就醒來；預設在全螢幕時自動隱藏。
- 點「檢查更新」後，有新版會顯示「更新」，再點即可自動下載、替換並重啟。

找不到系統匣圖示時，請查看工作列的「顯示隱藏的圖示」。設定與記錄存放於 `%LOCALAPPDATA%\chuh0o`。

## 使用 Python 執行

需要 **Windows 11、Python 3.12 以上的 64 位元版本**。在專案目錄開啟 PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe src\main.py
```

若使用其他 Python 版本，將第一行改為對應的 `py -3.x`，或直接使用 Python 執行檔的完整路徑。
開發測試時可加上 `--dev-actions` 顯示動作選單；發布版不提供此選單。
原始碼模式可檢查版本，但不會自動替換開發檔案。

## 開發

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

打包結果位於 `dist/`，請分發完整 ZIP。
更多設計說明：[狀態機與物理](docs/PHYSICS.md)、[更新流程](docs/UPDATES.md)。
