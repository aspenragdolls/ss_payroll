# Creates a desktop shortcut for Launch SS Payroll.bat
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LauncherBat = Join-Path $ProjectRoot "Launch SS Payroll.bat"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "SS Payroll.lnk"

if (-not (Test-Path $LauncherBat)) {
    Write-Host "Launcher not found: $LauncherBat" -ForegroundColor Red
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $LauncherBat
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = "Start SS Payroll local development server"
$shortcut.WindowStyle = 1

$pythonIcon = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $pythonIcon) {
    $shortcut.IconLocation = "$pythonIcon,0"
} else {
    $shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
}

$shortcut.Save()

Write-Host "Desktop shortcut created:"
Write-Host "  $ShortcutPath"
