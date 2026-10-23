# Zero Lab installer for Windows 10/11: WSL2 + Ubuntu, then builds Zero Lab inside it (setup.sh)
# and adds "Zero Lab" shortcuts to the desktop and Start menu.
# Started by double-clicking "Install Zero Lab (Windows).cmd".
#Requires -Version 5.1
# -DryRun lists every change it would make and changes nothing.
param([string]$Distro = '', [int]$Port = 8642, [switch]$DryRun)  # default distro: an existing Ubuntu, else a new "Ubuntu"
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:WSL_UTF8 = '1'   # make wsl.exe print UTF-8 instead of UTF-16
function Say($m) { Write-Host "==> $m" -ForegroundColor Magenta }
function Ask($q) { if ($DryRun) { return $true }; (Read-Host "$q [Y/n]") -notmatch '^[nN]' }
function Change($what, [scriptblock]$do) {
  if ($DryRun) { Write-Host "DRY-RUN would: $what" -ForegroundColor Yellow } else { & $do }
}

# 1. WSL itself
$null = & wsl.exe --status 2>&1
if ($LASTEXITCODE -ne 0) {
  Say 'Zero Lab runs its Raspberry Pi inside the Windows Subsystem for Linux (WSL2).'
  if (-not (Ask 'Install WSL2 now? Windows will ask for administrator permission and may need a restart.')) { exit 1 }
  Change 'install the WSL feature (wsl.exe --install --no-distribution, elevated)' {
    Start-Process wsl.exe -ArgumentList '--install', '--no-distribution' -Verb RunAs -Wait }
  Say 'WSL is installed. If Windows asks you to restart, restart, then double-click "Install Zero Lab" again.'
  exit 0
}

# 2. The Ubuntu distribution (WSL version 2): reuse one the user already has (Ubuntu, Ubuntu-24.04, ...)
$distros = (& wsl.exe --list --quiet) -split "`r?`n" | ForEach-Object { $_.Trim([char]0, ' ') } | Where-Object { $_ }
if (-not $Distro) {
  $Distro = @($distros | Where-Object { $_ -eq 'Ubuntu' }) + @($distros | Where-Object { $_ -like 'Ubuntu*' }) | Select-Object -First 1
  if (-not $Distro) { $Distro = 'Ubuntu' }
}
Say "Using WSL distribution: $Distro"
if ($distros -notcontains $Distro) {
  if (-not (Ask "Install Ubuntu in WSL now (about 1 GB)?")) { exit 1 }
  Say 'Ubuntu will ask you to choose a Linux user name and password. When you see a prompt ending in $, type exit and press Enter.'
  Change "install WSL distribution $Distro (wsl.exe --install -d $Distro)" {
    & wsl.exe --install -d $Distro
    if ($LASTEXITCODE -ne 0) { throw 'Installing Ubuntu failed.' } }
}
$verbose = (& wsl.exe --list --verbose) -join "`n"
if ($verbose -notmatch "$Distro\s+\S+\s+2") {
  Change "convert $Distro to WSL 2 (wsl.exe --set-version $Distro 2)" { & wsl.exe --set-version $Distro 2 }
}

# 3. Build and install inside Ubuntu (prompts for the Linux password once, for apt)
Say 'Building Zero Lab inside Ubuntu. The first time takes 10-40 minutes.'
Change "run setup.sh inside ${Distro}: apt build packages, build QEMU into ~/.local/share/zero-lab, add ~/.local/bin/zero-lab" {
  & wsl.exe -d $Distro --cd "$Here" -- bash setup.sh
  if ($LASTEXITCODE -ne 0) { throw 'setup.sh failed; see the messages above.' } }

# 4. Launcher and shortcuts
$dest = Join-Path $env:LOCALAPPDATA 'Zero Lab'
$launcher = Join-Path $dest 'Zero Lab.cmd'
$desktopLinks = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) | ForEach-Object { Join-Path $_ 'Zero Lab.lnk' }
if ($DryRun) {
  Change "create $dest with icon.ico and Zero Lab.cmd (runs: wsl.exe -d $Distro -- ~/.local/bin/zero-lab --port $Port)" {}
  $desktopLinks | ForEach-Object { Change "create shortcut $_" {} }
  Say 'Dry run finished; nothing was changed.'
  exit 0
}
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $Here 'zero-lab\icon.ico') $dest -Force
@"
@echo off
title Zero Lab - close this window to stop the Pi
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "`$u='http://127.0.0.1:$Port/'; foreach (`$i in 1..60) { try { `$null = Invoke-WebRequest `$u -UseBasicParsing -TimeoutSec 2; break } catch { Start-Sleep 1 } }; Start-Process `$u"
wsl.exe -d $Distro -- ~/.local/bin/zero-lab --port $Port
"@ | Set-Content -Encoding ASCII $launcher
$shell = New-Object -ComObject WScript.Shell
foreach ($path in $desktopLinks) {
  $lnk = $shell.CreateShortcut($path)
  $lnk.TargetPath = $launcher
  $lnk.IconLocation = (Join-Path $dest 'icon.ico')
  $lnk.WorkingDirectory = $dest
  $lnk.WindowStyle = 7   # start minimized; the browser shows the app
  $lnk.Save()
}
Say 'Done! Double-click "Zero Lab" on your desktop. It opens in your web browser.'
