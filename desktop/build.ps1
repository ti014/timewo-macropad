# Build the portable Windows folder; uv.lock pins the tested dependencies.
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    uv run pyinstaller --noconfirm --windowed --onedir --distpath dist/v0.9 --name MacropadConfigurator --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 main.py
    if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
} finally {
    Pop-Location
}
