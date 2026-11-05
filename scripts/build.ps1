$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv with Python 3.12+ and install .[dev] first. See README.md.'
}
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot '.pyinstaller'
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
$pythonInstall = & $pythonPath -c 'import sys; print(sys.base_prefix)'
if ($LASTEXITCODE -ne 0) { throw 'Python inspection failed' }
# Avoid collecting unrelated DLLs from tools such as Poppler on the caller's PATH.
$env:PATH = "$projectRoot\.venv\Scripts;$pythonInstall;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
& $pythonPath scripts/make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
& $pythonPath -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $pythonPath -m PyInstaller --noconfirm chuh0o.spec
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
Copy-Item -LiteralPath 'README.md' -Destination 'dist\chuh0o'
# Remove the local validation report if an older build left it in the output.
$oldValidationReport = Join-Path $projectRoot 'dist\chuh0o\VALIDATION.md'
if (Test-Path -LiteralPath $oldValidationReport) {
    Remove-Item -LiteralPath $oldValidationReport -Force
}
$appVersion = & $pythonPath -c "import sys; sys.path.insert(0, 'src'); from chuh0o import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Version inspection failed' }
$releaseArchive = 'dist\chuh0o-v{0}-windows-x64.zip' -f $appVersion
Compress-Archive -Path 'dist\chuh0o' -DestinationPath $releaseArchive -Force
Write-Output 'Ready: dist\chuh0o\chuh0o.exe (distribute the complete folder or ZIP)'
