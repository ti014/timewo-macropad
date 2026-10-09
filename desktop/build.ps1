# Build a standalone Windows executable; uv.lock pins the tested dependencies.
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    uv run pyinstaller --noconfirm --windowed --onefile --distpath dist/v0.10-single --workpath build/v0.10-single --specpath build/v0.10-single --name timewo-macropad-v0.10.0-windows-x64 --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 --hidden-import bleak.backends.winrt.client --hidden-import bleak.backends.winrt.scanner main.py
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
} finally {
    Pop-Location
}
