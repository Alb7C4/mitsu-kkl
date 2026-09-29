# Builds the Windows release: two standalone .exe files (no Python needed) packed in a zip.
#
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
#
# The version comes from kkl/__init__.py (__version__); the GitHub release tag must be v<version>.
# PyInstaller works in %TEMP%\mitsu-kkl-build; the finished folder and zip are copied to .\dist
# (ignored by git).
$ErrorActionPreference = "Stop"

$src = $PSScriptRoot
$m = Select-String -Path (Join-Path $src "kkl\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $m) { throw "__version__ not found in kkl\__init__.py" }
$Version = $m.Matches[0].Groups[1].Value
$work = Join-Path $env:TEMP "mitsu-kkl-build"
$dist = Join-Path $work "dist"

python -m pip install --quiet --upgrade pyinstaller pyserial
if ($LASTEXITCODE) { throw "pip install failed" }

# The GUI carries both READMEs inside the .exe for its welcome window.
$readmes = @("--add-data", "$src\README.md;.", "--add-data", "$src\README.pl.md;.")
$apps = @(
    @{ Name = "mut_gui";   Mode = "--windowed"; Extra = $readmes },   # GUI, no console window
    @{ Name = "kkl_probe"; Mode = "--console";  Extra = @() }         # command-line probe
)
foreach ($app in $apps) {
    $extra = $app.Extra
    python -m PyInstaller --noconfirm --clean --onefile $app.Mode --name $app.Name @extra `
        --distpath $dist --workpath (Join-Path $work "build") --specpath $work `
        (Join-Path $src "$($app.Name).py")
    if ($LASTEXITCODE) { throw "PyInstaller failed for $($app.Name)" }
}

$name = "mitsu-kkl-$Version-windows"
$pkg = Join-Path $work $name
if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory $pkg | Out-Null
Copy-Item (Join-Path $dist "mut_gui.exe"), (Join-Path $dist "kkl_probe.exe") $pkg
foreach ($f in "README.md", "README.pl.md", "INSTRUKCJA.md", "PID_znaczenia.md", "LICENSE", "dtc_definitions.csv") {
    Copy-Item (Join-Path $src $f) $pkg
}

# Ship the PID names found so far, with only a short basic list switched on
# (all ~170 PIDs on the list would make one polling cycle take ~0.8 s).
$env:PYTHONPATH = $src
python -c @"
from kkl import piddefs
defs, problems, keep, _ = piddefs.load_defs(r'$src\pid_definicje.csv')
basic = {0x07, 0x10, 0x11, 0x14, 0x15, 0x17, 0x21, 0x24, 0x40, 0x45}
for pid, d in defs.items():
    d.active = pid in basic
piddefs.save_defs(r'$pkg\pid_definitions.csv', defs, keep)
"@
if ($LASTEXITCODE) { throw "writing pid_definitions.csv failed" }

$zip = Join-Path $work "$name.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $pkg "*") -DestinationPath $zip

$out = Join-Path $src "dist"
New-Item -ItemType Directory $out -Force | Out-Null
if (Test-Path (Join-Path $out $name)) { Remove-Item (Join-Path $out $name) -Recurse -Force }
Copy-Item $pkg $out -Recurse
Copy-Item $zip $out -Force
Write-Output "built: $(Join-Path $out "$name.zip")"
Write-Output "exe:   $(Join-Path $out $name)"
