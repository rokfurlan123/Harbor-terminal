#!/usr/bin/env python3
"""Create the Windows desktop entry; all application code runs in WSL."""
import base64
import subprocess

script = r'''
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Codex Workspace.lnk'
$terminal = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\wt.exe'
if (-not (Test-Path $terminal)) { throw 'Windows Terminal is not installed.' }
$arguments = '-w new new-tab --title "Codex Workspace" wsl.exe -d Ubuntu --cd /home/rokdbest/codex-workspace --exec bash -lic "exec /home/rokdbest/bin/codex-workspace"'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $terminal
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $env:USERPROFILE
$shortcut.Description = 'Codex conversations with a saved-session sidebar (Ubuntu WSL)'
$shortcut.IconLocation = "$env:SystemRoot\System32\wsl.exe,0"
$shortcut.Save()
$verified = $shell.CreateShortcut($shortcutPath)
if (-not (Test-Path $shortcutPath) -or $verified.TargetPath -ne $terminal -or $verified.Arguments -ne $arguments) {
    throw 'Desktop shortcut verification failed.'
}
[PSCustomObject]@{Shortcut=$shortcutPath; Target=$verified.TargetPath; Arguments=$verified.Arguments} | ConvertTo-Json
'''
encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], check=True)
