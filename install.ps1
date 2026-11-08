# Create a Startup shortcut that launches the app silently with pythonw.
$ErrorActionPreference = "Stop"
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $py = (Get-Command python.exe).Source
    $pythonw = Join-Path (Split-Path $py) "pythonw.exe"
}
$startup = [Environment]::GetFolderPath("Startup")
$linkPath = Join-Path $startup "Muse Voice Paste.lnk"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
$link.TargetPath = $pythonw
$link.Arguments = '"' + (Join-Path $appDir "main.py") + '"'
$link.WorkingDirectory = $appDir
$link.Description = "Muse Voice Paste - push-to-talk dictation"
$link.Save()
Write-Host "スタートアップに登録しました: $linkPath"
