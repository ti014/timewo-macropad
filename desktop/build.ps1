# Build a standalone Windows executable; uv.lock pins the tested dependencies.
# Run ../build-firmware.ps1 first so the EXE ships with ready-to-flash firmware.
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $dist = 'dist/v0.11-single'
    # esptool loads its flasher stubs from JSON data files at runtime.
    uv run pyinstaller --noconfirm --windowed --onefile --distpath $dist --workpath build/v0.11-single --specpath build/v0.11-single --name timewo-macropad-v0.11.0-windows-x64 --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 --hidden-import bleak.backends.winrt.client --hidden-import bleak.backends.winrt.scanner --collect-data esptool --collect-submodules esptool main.py
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
    # The flasher looks for packages in "firmware" next to the EXE.
    $firmware = Join-Path $PSScriptRoot '..\dist\firmware'
    if (Test-Path $firmware) {
        $target = Join-Path $dist 'firmware'
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Copy-Item -Recurse $firmware $target
    } else {
        Write-Warning 'No ../dist/firmware; run ../build-firmware.ps1 to bundle firmware packages.'
    }
} finally {
    Pop-Location
}
