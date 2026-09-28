# Builds the Windows release: two standalone .exe files (no Python needed) packed in a zip.
#
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1 -Version 0.1.0
#
# Build files go to %TEMP%\mitsu-kkl-build (not into this folder, which may sit in a synced
# drive). The script prints the path of the finished zip.
param([string]$Version = "dev")
$ErrorActionPreference = "Stop"

$src = $PSScriptRoot
$work = Join-Path $env:TEMP "mitsu-kkl-build"
$dist = Join-Path $work "dist"

python -m pip install --quiet --upgrade pyinstaller pyserial
if ($LASTEXITCODE) { throw "pip install failed" }

$apps = @(
    @{ Name = "mut_gui";   Mode = "--windowed" },   # GUI, no console window
    @{ Name = "kkl_probe"; Mode = "--console" }     # command-line probe
)
foreach ($app in $apps) {
    python -m PyInstaller --noconfirm --clean --onefile $app.Mode --name $app.Name `
        --distpath $dist --workpath (Join-Path $work "build") --specpath $work `
        (Join-Path $src "$($app.Name).py")
    if ($LASTEXITCODE) { throw "PyInstaller failed for $($app.Name)" }
}

$pkg = Join-Path $work "mitsu-kkl-$Version-windows"
if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory $pkg | Out-Null
Copy-Item (Join-Path $dist "mut_gui.exe"), (Join-Path $dist "kkl_probe.exe") $pkg
foreach ($f in "README.md", "README.pl.md", "PID_znaczenia.md", "LICENSE", "dtc_definitions.csv") {
    Copy-Item (Join-Path $src $f) $pkg
}

# Ship the PID names found so far, with only a short basic list switched on
# (all ~170 PIDs on the list would make one polling cycle take ~0.8 s).
$env:PYTHONPATH = $src
python -c @"
import sys
from kkl import piddefs
defs, problems, keep, _ = piddefs.load_defs(r'$src\pid_definicje.csv')
basic = {0x07, 0x10, 0x11, 0x14, 0x15, 0x17, 0x21, 0x24, 0x40, 0x45}
for pid, d in defs.items():
    d.active = pid in basic
piddefs.save_defs(r'$pkg\pid_definitions.csv', defs, keep)
"@
if ($LASTEXITCODE) { throw "writing pid_definitions.csv failed" }

$zip = Join-Path $work "mitsu-kkl-$Version-windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $pkg "*") -DestinationPath $zip
Write-Output "built: $zip"
