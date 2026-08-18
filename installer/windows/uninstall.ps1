<#
.SYNOPSIS
    Removes Claude Limit Watcher for the current user.

.DESCRIPTION
    Stops the app, deletes the install folder and shortcuts, and removes the
    logon and uninstall registry entries.

    Saved accounts and settings in %LOCALAPPDATA%\ClimitWatch are kept unless
    -Purge is given, so reinstalling picks up where you left off. Nothing in
    ~/.claude is ever touched.

.PARAMETER Purge
    Also delete saved accounts, settings and the snapshot cache.
#>
[CmdletBinding()]
param([switch]$Purge)

$ErrorActionPreference = 'Stop'

$AppName    = 'ClimitWatch'
$AppDisplay = 'Claude Limit Watcher'
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"
$DataDir    = Join-Path $env:LOCALAPPDATA $AppName
$RunKey     = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$ApprovedKey= 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'
$ApprovedFolderKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'
$UninstKey  = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"

function Write-Step($message) { Write-Host "  $message" }

Write-Host "Uninstalling $AppDisplay" -ForegroundColor Cyan

$running = Get-Process -Name $AppName -ErrorAction SilentlyContinue
if ($running) {
    Write-Step 'Stopping the running copy'
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 700
}

Write-Step 'Removing logon entry'
Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue
# Drop the inventory record too, or Settings keeps showing a dead
# "Registry Location: ...\Run\ClimitWatch" row forever.
Remove-ItemProperty -Path $ApprovedKey -Name $AppName -ErrorAction SilentlyContinue

Remove-ItemProperty -Path $ApprovedFolderKey -Name "$AppDisplay.lnk" -ErrorAction SilentlyContinue

Write-Step 'Removing shortcuts'
$shortcuts = @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppDisplay.lnk"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\$AppDisplay.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppDisplay.lnk")
)
foreach ($shortcut in $shortcuts) {
    if (Test-Path $shortcut) { Remove-Item $shortcut -Force }
}

Write-Step 'Removing uninstall entry'
if (Test-Path $UninstKey) { Remove-Item $UninstKey -Recurse -Force }

if ($Purge) {
    Write-Step 'Deleting saved accounts and settings'
    if (Test-Path $DataDir) { Remove-Item $DataDir -Recurse -Force }
} elseif (Test-Path $DataDir) {
    Write-Step "Keeping settings and accounts in $DataDir (use -Purge to delete)"
}

# The uninstaller lives inside the folder it is deleting, so hand the last step
# to a detached shell that waits for this process to exit.
if (Test-Path $InstallDir) {
    Write-Step "Removing $InstallDir"
    $cmd = "Start-Sleep -Milliseconds 800; Remove-Item -LiteralPath '$InstallDir' -Recurse -Force -ErrorAction SilentlyContinue"
    Start-Process -WindowStyle Hidden powershell -ArgumentList '-NoProfile', '-Command', $cmd
}

Write-Host ''
Write-Host "$AppDisplay removed." -ForegroundColor Green
