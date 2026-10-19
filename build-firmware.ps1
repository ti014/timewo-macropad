# Build every board env in platformio.ini and package it for the desktop app's
# "Nạp firmware" dialog: dist/firmware/<env>/{manifest.json, *.bin}.
#   ./build-firmware.ps1                 # all envs
#   ./build-firmware.ps1 -Env ti-clicker  # one env
param([string[]]$Env = @())
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $pio = Join-Path $env:USERPROFILE '.platformio\penv\Scripts\pio.exe'
    if (-not (Test-Path $pio)) { $pio = 'pio' }
    $bootApp0 = Join-Path $env:USERPROFILE '.platformio\packages\framework-arduinoespressif32\tools\partitions\boot_app0.bin'
    # Board definition -> chip, and where that chip's ROM looks for the bootloader.
    $chips = @{
        'esp32-c3-devkitm-1' = @{ chip = 'esp32c3'; bootloader = 0x0 }
        'esp32-s3-devkitc-1' = @{ chip = 'esp32s3'; bootloader = 0x0 }
        'esp32dev'           = @{ chip = 'esp32'; bootloader = 0x1000 }
    }

    $version = [regex]::Match((Get-Content -Raw 'include/config.h'), 'kFirmwareVersion\[\] = "([^"]+)"').Groups[1].Value
    if (-not $version) { throw 'kFirmwareVersion not found in include/config.h' }

    # Split platformio.ini into [env:<name>] sections.
    $sections = [ordered]@{}
    $current = $null
    foreach ($line in Get-Content 'platformio.ini') {
        if ($line -match '^\[env:([^\]]+)\]') { $current = $Matches[1]; $sections[$current] = '' }
        elseif ($line -match '^\[') { $current = $null }
        elseif ($current) { $sections[$current] += "$line`n" }
    }
    $targets = if ($Env.Count) { $Env } else { @($sections.Keys) }

    $out = Join-Path $PSScriptRoot 'dist\firmware'
    New-Item -ItemType Directory -Force $out | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding($false)

    foreach ($name in $targets) {
        if (-not $sections.Contains($name)) { throw "Unknown env: $name" }
        $text = $sections[$name]
        $board = [regex]::Match($text, '(?m)^board\s*=\s*(\S+)').Groups[1].Value
        if (-not $chips.ContainsKey($board)) { throw "Env $name uses board '$board' with no chip mapping in this script." }
        $pins = [regex]::Match($text, 'MACROPAD_PINS=([\d,]+)').Groups[1].Value
        if (-not $pins) { $pins = '3,4,5,6' }
        $title = [regex]::Match($text, 'MACROPAD_NAME="([^"]+)"').Groups[1].Value
        if (-not $title) { $title = 'timewo-macropad' }
        $boardId = [regex]::Match($text, 'MACROPAD_BOARD=''"([^"]+)"''').Groups[1].Value
        if (-not $boardId) { $boardId = 'macropad4' }

        & $pio run -e $name
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $name" }

        $build = Join-Path $PSScriptRoot ".pio\build\$name"
        $dest = Join-Path $out $name
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        New-Item -ItemType Directory -Force $dest | Out-Null
        Copy-Item (Join-Path $build 'bootloader.bin'), (Join-Path $build 'partitions.bin'), (Join-Path $build 'firmware.bin') $dest
        Copy-Item $bootApp0 $dest

        function Entry($file, $offset) {
            $hash = (Get-FileHash -Algorithm SHA256 (Join-Path $dest $file)).Hash.ToLower()
            [ordered]@{ file = $file; offset = ('0x{0:x}' -f [int]$offset); sha256 = $hash }
        }
        $app = Entry 'firmware.bin' 0x10000
        $manifest = [ordered]@{
            schema  = 1
            board   = $boardId
            env     = $name
            title   = $title
            chip    = $chips[$board].chip
            version = $version
            pins    = @($pins.Split(',') | ForEach-Object { [int]$_ })
            app     = $app
            full    = @(
                (Entry 'bootloader.bin' $chips[$board].bootloader),
                (Entry 'partitions.bin' 0x8000),
                (Entry 'boot_app0.bin' 0xe000),
                $app
            )
        }
        [IO.File]::WriteAllText((Join-Path $dest 'manifest.json'), ($manifest | ConvertTo-Json -Depth 5), $utf8)
        Write-Host "Packaged $name ($($chips[$board].chip), v$version) -> $dest"
    }
} finally {
    Pop-Location
}
