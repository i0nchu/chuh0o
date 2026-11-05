param([string]$PlanPath)
$ErrorActionPreference = 'Stop'
$script:UpdateHelperRoot = [IO.Path]::GetFullPath($PSScriptRoot)

function Test-WithinFolder([string]$Child, [string]$Parent) {
    $childPath = [IO.Path]::GetFullPath($Child)
    $parentPath = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    return $childPath.StartsWith($parentPath + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Assert-AppChild([string]$Path, [string]$Parent) {
    $absolute = [IO.Path]::GetFullPath($Path)
    if (-not [IO.Path]::GetDirectoryName($absolute).TrimEnd('\').Equals(
        [IO.Path]::GetFullPath($Parent).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Update target is outside the application parent directory.'
    }
    if ((Test-Path -LiteralPath $absolute) -and
        ((Get-Item -LiteralPath $absolute).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Updating a linked directory is not supported.'
    }
}

function Move-AppFolder([string]$Source, [string]$Destination, [string]$Parent) {
    Assert-AppChild $Source $Parent
    Assert-AppChild $Destination $Parent
    $retryUntil = [DateTime]::UtcNow.AddSeconds(20)
    while ($true) {
        try {
            Move-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
            return
        } catch {
            if ([DateTime]::UtcNow -ge $retryUntil) { throw }
            Start-Sleep -Milliseconds 300
        }
    }
}

function Remove-AppFolder([string]$Path, [string]$Parent) {
    Assert-AppChild $Path $Parent
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
    }
}

function Start-Pet([string]$Executable, [string]$DataDirectory, [string]$ReadyFile) {
    $petArguments = '--data-dir "{0}"' -f $DataDirectory
    if ($ReadyFile) { $petArguments += ' --update-ready-file "{0}"' -f $ReadyFile }
    return Start-Process -FilePath $Executable -ArgumentList $petArguments `
        -WorkingDirectory (Split-Path -Parent $Executable) -WindowStyle Hidden -PassThru
}

function Wait-PetExit($Process) {
    if ($null -ne $Process -and -not $Process.WaitForExit(60000)) {
        throw 'The running pet did not exit. No files were replaced.'
    }
}

function Wait-PetReady($Process, [string]$ReadyFile, [string]$Version) {
    $until = [DateTime]::UtcNow.AddSeconds(20)
    while ([DateTime]::UtcNow -lt $until) {
        $Process.Refresh()
        if ($Process.HasExited) { return $false }
        if (Test-Path -LiteralPath $ReadyFile) {
            try {
                $ready = Get-Content -LiteralPath $ReadyFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($ready.version -eq $Version -and $ready.pid -eq $Process.Id) { return $true }
            } catch { } # The marker may still be in the middle of its write.
        }
        Start-Sleep -Milliseconds 200
    }
    return $false
}

function Stop-UpdatedPet($Process, [string]$ExpectedExecutable) {
    if ($null -eq $Process) { return }
    $Process.Refresh()
    if (-not $Process.HasExited -and $Process.Path -eq $ExpectedExecutable) {
        Stop-Process -Id $Process.Id -Force
        $null = $Process.WaitForExit(5000)
    }
}

function Write-UpdateResult([string]$Status, [string]$Message) {
    $result = @{ status = $Status; message = $Message } | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $script:UpdateHelperRoot 'result.json'), $result,
                           [Text.UTF8Encoding]::new($false))
}

function Invoke-PetUpdate([string]$PlanPath) {
    $oldMoved = $false
    $newMoved = $false
    $incomingCreated = $false
    $newProcess = $null
    $oldProcess = $null
    $mutex = $null
    $mutexOwned = $false
    $pathsValidated = $false
    try {
        $planAbsolute = [IO.Path]::GetFullPath($PlanPath)
        if ((Split-Path -Parent $planAbsolute) -ne $script:UpdateHelperRoot) {
            throw 'Update plan must be beside the helper.'
        }
        $jobId = Split-Path -Leaf $script:UpdateHelperRoot
        if ($jobId -notmatch '^[a-f0-9]{32}$') { throw 'Invalid update job directory.' }
        $plan = Get-Content -LiteralPath $planAbsolute -Raw -Encoding UTF8 | ConvertFrom-Json
        $appDirectory = [IO.Path]::GetFullPath($plan.app_dir).TrimEnd('\')
        $parentDirectory = Split-Path -Parent $appDirectory
        $stagedDirectory = [IO.Path]::GetFullPath($plan.staged_dir).TrimEnd('\')
        $dataDirectory = [IO.Path]::GetFullPath($plan.data_dir).TrimEnd('\')
        if (-not $parentDirectory -or $appDirectory -eq [IO.Path]::GetPathRoot($appDirectory)) {
            throw 'Invalid application directory.'
        }
        if (-not (Test-WithinFolder $script:UpdateHelperRoot (Join-Path $dataDirectory 'updates')) -or
            -not (Test-WithinFolder $stagedDirectory (Join-Path $script:UpdateHelperRoot 'unpacked'))) {
            # A flat archive can use the unpacked directory itself.
            if ($stagedDirectory -ne (Join-Path $script:UpdateHelperRoot 'unpacked') -or
                -not (Test-WithinFolder $script:UpdateHelperRoot (Join-Path $dataDirectory 'updates'))) {
                throw 'Staging directory is outside the update job.'
            }
        }
        if ($dataDirectory -eq $appDirectory -or (Test-WithinFolder $dataDirectory $appDirectory) -or
            (Test-WithinFolder $script:UpdateHelperRoot $appDirectory) -or
            (Test-Path -LiteralPath (Join-Path $appDirectory '.git'))) {
            throw 'Settings and source checkouts must not be inside the application update target.'
        }
        if ($plan.new_version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid update version.' }
        $executable = Join-Path $appDirectory 'chuh0o.exe'
        foreach ($directory in @($appDirectory, $stagedDirectory)) {
            if (-not (Test-Path -LiteralPath (Join-Path $directory 'chuh0o.exe')) -or
                -not (Test-Path -LiteralPath (Join-Path $directory '_internal\assets\manifest.json'))) {
                throw 'Application bundle is incomplete.'
            }
        }
        Assert-AppChild $appDirectory $parentDirectory
        $backupDirectory = Join-Path $parentDirectory ('.{0}.backup-{1}' -f (Split-Path -Leaf $appDirectory), $jobId)
        $incomingDirectory = Join-Path $parentDirectory ('.{0}.incoming-{1}' -f (Split-Path -Leaf $appDirectory), $jobId)
        Assert-AppChild $backupDirectory $parentDirectory
        Assert-AppChild $incomingDirectory $parentDirectory
        if ((Test-Path -LiteralPath $backupDirectory) -or (Test-Path -LiteralPath $incomingDirectory)) {
            throw 'A previous update is still pending.'
        }
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($appDirectory.ToLowerInvariant()))).Replace('-', '') }
        finally { $sha.Dispose() }
        $mutex = [Threading.Mutex]::new($false, ('Local\chuh0o-update-' + $hash.Substring(0, 20)))
        $mutexOwned = $mutex.WaitOne(0)
        if (-not $mutexOwned) { throw 'Another updater is using this application directory.' }
        $oldProcess = Get-Process -Id $plan.parent_pid -ErrorAction SilentlyContinue
        if ($null -ne $oldProcess -and $oldProcess.Path -ne $executable) {
            throw 'Parent process does not match the installed pet.'
        }
        $pathsValidated = $true
        # Copy across volumes into a sibling first, then swap using same-volume renames.
        $incomingCreated = $true
        Copy-Item -LiteralPath $stagedDirectory -Destination $incomingDirectory -Recurse
        Wait-PetExit $oldProcess
        Move-AppFolder $appDirectory $backupDirectory $parentDirectory
        $oldMoved = $true
        Move-AppFolder $incomingDirectory $appDirectory $parentDirectory
        $newMoved = $true
        $readyFile = Join-Path $script:UpdateHelperRoot 'ready.json'
        $newProcess = Start-Pet $executable $dataDirectory $readyFile
        if (-not (Wait-PetReady $newProcess $readyFile $plan.new_version)) {
            throw 'The updated pet could not start; restoring the previous version.'
        }
        Write-UpdateResult 'updated' ''
        # Failure to remove a backup does not invalidate a healthy new installation.
        try { Remove-AppFolder $backupDirectory $parentDirectory } catch { }
        $unpacked = [IO.Path]::GetFullPath((Join-Path $script:UpdateHelperRoot 'unpacked'))
        if (Test-WithinFolder $unpacked $script:UpdateHelperRoot) {
            try { Remove-Item -LiteralPath $unpacked -Recurse -Force } catch { }
        }
        $archive = Join-Path $script:UpdateHelperRoot 'package.zip'
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
        return 0
    } catch {
        $failure = $_.Exception.Message
        if ($pathsValidated) {
            try {
                Stop-UpdatedPet $newProcess $executable
                if ($newMoved) { Remove-AppFolder $appDirectory $parentDirectory }
                if ($oldMoved) { Move-AppFolder $backupDirectory $appDirectory $parentDirectory }
                if ($incomingCreated -and (Test-Path -LiteralPath $incomingDirectory)) {
                    Remove-AppFolder $incomingDirectory $parentDirectory
                }
                Wait-PetExit $oldProcess
                $null = Start-Pet $executable $dataDirectory ''
            } catch { $failure += ' Recovery: ' + $_.Exception.Message }
        }
        Write-UpdateResult 'failed' $failure
        return 1
    } finally {
        if ($mutexOwned) { $mutex.ReleaseMutex() }
        if ($null -ne $mutex) { $mutex.Dispose() }
    }
}

if ($MyInvocation.InvocationName -ne '.') { exit (Invoke-PetUpdate -PlanPath $PlanPath) }
