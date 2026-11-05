$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$entryPath = Join-Path $projectRoot 'src\main.py'
$dataDirectory = Join-Path $projectRoot 'local-data-physics-preview'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create .venv and install the project dependencies first. See README.md.'
}
$previewArguments = '"{0}" --data-dir "{1}" --dev-actions' -f $entryPath, $dataDirectory
$previewProcess = Start-Process -FilePath $pythonPath -ArgumentList $previewArguments `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
Write-Output "Source preview process: $($previewProcess.Id). Exit from the bunny tray menu."
