# Windows undo: re-enables every app taxis disabled (latest snapshot).
# Usage: powershell -ExecutionPolicy Bypass -File restore.ps1 [-Device 192.168.1.50] [-File path\to\x.restore.txt]
param([string]$Device = $env:TAXIS_TV, [string]$File = "")
$dir = Join-Path $HOME ".taxis\snapshots"
$s = @()
if ($Device) {
  if ($Device -notmatch ":") { $Device = "${Device}:5555" }
  $s = @("-s", $Device)
}
if (-not $File) {
  $files = Get-ChildItem "$dir\*.restore.txt" -ErrorAction SilentlyContinue
  if ($Device) {
    $prefix = ($Device -replace ':', '_') + '_'
    $files = $files | Where-Object { $_.Name.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) }
  }
  $f = $files | Sort-Object LastWriteTime | Select-Object -Last 1
  if ($f) { $File = $f.FullName }
}
if (-not $File -or -not (Test-Path $File)) { Write-Host "No restore file found in $dir"; exit 1 }
if ($Device) {
  adb connect $Device | Out-Null
}
Write-Host "Re-enabling packages from $File"
Get-Content $File | Where-Object { $_.Trim() } | ForEach-Object {
  $pkg = $_.Trim()
  if ($pkg -match '^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$') {
    $out = adb @s shell pm enable $pkg 2>&1
    Write-Host "  $pkg -> $out"
  } else {
    Write-Warning "Skipping invalid package name: $pkg"
  }
}
Write-Host "Done. Restart the TV to be safe."
