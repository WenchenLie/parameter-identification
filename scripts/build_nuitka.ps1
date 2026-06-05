$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Entry = Join-Path $Root "main.py"
$OutputDir = Join-Path $Root "dist"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PyProject = Join-Path $Root "pyproject.toml"
$License = Join-Path $Root "LICENSE"

if (-not (Test-Path $Python)) {
  throw "Virtual environment python not found: $Python. Run: uv venv --python 3.14 .venv"
}

$VersionMatch = Select-String -Path $PyProject -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $VersionMatch) {
  throw "Project version not found in: $PyProject"
}

$AppVersion = $VersionMatch.Matches[0].Groups[1].Value
$NumericVersion = ($AppVersion -split "[-+]")[0]
$VersionParts = @($NumericVersion -split "\.")
if ($VersionParts.Count -gt 4 -or ($VersionParts | Where-Object { $_ -notmatch '^\d+$' })) {
  throw "Nuitka Windows file version must be numeric, got: $AppVersion"
}
while ($VersionParts.Count -lt 4) {
  $VersionParts += "0"
}
$WindowsVersion = $VersionParts -join "."
$FileSafeVersion = $AppVersion -replace '[<>:"/\\|?*]', "_"
$OutputFileName = "HPI-v$FileSafeVersion.exe"

$env:PYTHONPATH = Join-Path $Root "src"

& $Python -m nuitka `
  --mode=onefile `
  --enable-plugin=pyqt5 `
  --windows-console-mode=disable `
  --include-package=parameter_identifier `
  --output-filename=$OutputFileName `
  --company-name="Wenchen Lie" `
  --product-name="Hysteresis Parameter Identification" `
  --file-description="Hysteresis Parameter Identification (HPI)" `
  --file-version=$WindowsVersion `
  --product-version=$WindowsVersion `
  --include-distribution-metadata=parameter-identifier `
  --include-package=matplotlib `
  --include-package=numpy `
  --include-package=PIL `
  --include-data-files="$Root\src\parameter_identifier\ui\main_window.ui=parameter_identifier/ui/main_window.ui" `
  --include-data-files="$Root\src\parameter_identifier\assets\app_icon.ico=parameter_identifier/assets/app_icon.ico" `
  --include-data-files="$Root\src\parameter_identifier\assets\app_icon.png=parameter_identifier/assets/app_icon.png" `
  --include-data-dir="$Root\assets=assets" `
  --include-data-dir="$Root\docs=docs" `
  --include-data-files="$License=LICENSE" `
  --include-data-files="$Root\resources\opensees\opensees.pyd=resources/opensees/opensees.pyd" `
  --include-data-files="$Root\resources\opensees\libiomp5md.dll=resources/opensees/libiomp5md.dll" `
  --windows-icon-from-ico="$Root\src\parameter_identifier\assets\app_icon.ico" `
  --output-dir="$OutputDir" `
  "$Entry"

if (Test-Path $License) {
  Copy-Item -Path $License -Destination (Join-Path $OutputDir "LICENSE") -Force
}
