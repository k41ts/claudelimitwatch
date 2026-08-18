<#
.SYNOPSIS
    Installs Claude Limit Watcher for the current user.

.DESCRIPTION
    Copies ClimitWatch.exe into %LOCALAPPDATA%\Programs\ClimitWatch, creates a
    Start Menu shortcut, registers an uninstall entry so it shows up in
    Settings > Apps, and (by default) starts the app at logon.

    Per-user on purpose: no admin rights, nothing written outside HKCU and the
    user profile.

.PARAMETER Source
    Path to ClimitWatch.exe. Defaults to ..\dist\ClimitWatch.exe.

.PARAMETER NoAutostart
    Skip the logon entry.

.PARAMETER NoDesktopShortcut
    Skip the desktop shortcut.

.PARAMETER NoLaunch
    Do not start the app after installing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\install.ps1
#>
[CmdletBinding()]
param(
    [string]$Source,
    [switch]$NoAutostart,
    [switch]$NoDesktopShortcut,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'

$AppName    = 'ClimitWatch'
$AppDisplay = 'Claude Limit Watcher'
$Version    = '0.1.0'
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$ExePath    = Join-Path $InstallDir "$AppName.exe"
$RunKey     = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$ApprovedKey= 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
$ApprovedFolderKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'
$UninstKey  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"

function Write-Step($message) { Write-Host "  $message" }

if (-not $Source) {
    $Source = Join-Path (Split-Path -Parent $PSScriptRoot) 'dist\ClimitWatch.exe'
}
if (-not (Test-Path $Source)) {
    throw "Could not find $Source. Build it first: pyinstaller --noconsole --onefile --name ClimitWatch --paths src launcher.py"
}

Write-Host "Installing $AppDisplay $Version for $env:USERNAME" -ForegroundColor Cyan

# Stop every running copy first. Beyond the file lock on the exe, the app is
# single-instance: a survivor (including one started from a source checkout via
# pythonw) would make the freshly installed exe hand over and exit immediately,
# which looks exactly like the install did nothing.
$stopped = 0
$running = Get-Process -Name $AppName -ErrorAction SilentlyContinue
if ($running) { $running | Stop-Process -Force; $stopped += $running.Count }

# Match only python processes that are actually running this app.
$pythonProcs = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'climitwatch|launcher\.py' }
foreach ($proc in $pythonProcs) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    $stopped++
}
if ($stopped -gt 0) {
    Write-Step "Stopped $stopped running instance(s)"
    Start-Sleep -Milliseconds 900
}

Write-Step "Copying to $InstallDir"
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
Copy-Item -Path $Source -Destination $ExePath -Force

# Ship the uninstaller next to the app so Apps & features can call it.
$uninstallSource = Join-Path $PSScriptRoot 'uninstall.ps1'
if (Test-Path $uninstallSource) {
    Copy-Item -Path $uninstallSource -Destination (Join-Path $InstallDir 'uninstall.ps1') -Force
}

function New-Shortcut([string]$Path, [string]$Target) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = Split-Path -Parent $Target
    $shortcut.Description = $AppDisplay
    $shortcut.Save()
}

$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
Write-Step 'Creating Start Menu shortcut'
New-Shortcut (Join-Path $startMenu "$AppDisplay.lnk") $ExePath

if (-not $NoDesktopShortcut) {
    Write-Step 'Creating desktop shortcut'
    New-Shortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppDisplay.lnk") $ExePath
}

if (-not $NoAutostart) {
    # A shortcut in the Startup folder rather than a Run value: it is visible in
    # Explorer, it carries the app name and icon, and Windows lists it in
    # Settings > Apps > Startup (a bare Run value did not show up here).
    Write-Step 'Enabling start at logon'
    $startupDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
    if (-not (Test-Path $startupDir)) { New-Item -ItemType Directory -Path $startupDir -Force | Out-Null }
    New-Shortcut (Join-Path $startupDir "$AppDisplay.lnk") $ExePath

    # 0x02 = enabled; without this record there is no On/Off state to show.
    New-Item -Path $ApprovedFolderKey -Force | Out-Null
    $enabled = [byte[]](2,0,0,0,0,0,0,0,0,0,0,0)
    Set-ItemProperty -Path $ApprovedFolderKey -Name "$AppDisplay.lnk" -Value $enabled -Type Binary

    # Drop the Run value older versions used, so nothing launches twice.
    Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $ApprovedKey -Name $AppName -ErrorAction SilentlyContinue
}

Write-Step 'Registering uninstall entry'
New-Item -Path $UninstKey -Force | Out-Null
$uninstallCmd = "powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstallDir\uninstall.ps1`""
Set-ItemProperty -Path $UninstKey -Name 'DisplayName'     -Value $AppDisplay
Set-ItemProperty -Path $UninstKey -Name 'DisplayVersion'  -Value $Version
Set-ItemProperty -Path $UninstKey -Name 'Publisher'       -Value 'local build'
Set-ItemProperty -Path $UninstKey -Name 'InstallLocation' -Value $InstallDir
Set-ItemProperty -Path $UninstKey -Name 'DisplayIcon'     -Value $ExePath
Set-ItemProperty -Path $UninstKey -Name 'UninstallString' -Value $uninstallCmd
Set-ItemProperty -Path $UninstKey -Name 'NoModify' -Value 1 -Type DWord
Set-ItemProperty -Path $UninstKey -Name 'NoRepair' -Value 1 -Type DWord
$sizeKb = [int]((Get-Item $ExePath).Length / 1KB)
Set-ItemProperty -Path $UninstKey -Name 'EstimatedSize' -Value $sizeKb -Type DWord

if (-not $NoLaunch) {
    Write-Step 'Starting the app'
    Start-Process -FilePath $ExePath
    Start-Sleep -Seconds 3
    if (-not (Get-Process -Name $AppName -ErrorAction SilentlyContinue)) {
        Write-Warning 'The app exited right after starting. Another instance may still hold the single-instance lock; close it and launch from the Start Menu.'
    }
}

Write-Host ''
Write-Host "Installed to $InstallDir" -ForegroundColor Green
Write-Host 'Uninstall from Settings > Apps, or run uninstall.ps1 in that folder.'
