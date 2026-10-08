# timewo-macropad

Firmware và ứng dụng cấu hình cho macropad 4 nút dùng ESP32-C3.

## Thành phần

- `src/`, `include/`: firmware PlatformIO cho ESP32-C3.
- `desktop/`: ứng dụng PySide6 cấu hình profile qua USB Serial.
- `Mo-Macropad.cmd`: chạy bản desktop đã build.

## Chạy desktop app

```powershell
cd desktop
uv sync --locked
uv run python main.py
```

Để build bản portable Windows:

```powershell
cd desktop
./build.ps1
```

## Nạp firmware

```powershell
pio run -t upload
```

Firmware hỗ trợ USB HID/Serial và BLE HID. Profile sửa trong desktop app chỉ có
hiệu lực BLE sau khi bấm `Đồng bộ board`. Các action `app` và `url` cần desktop
app trên máy chủ; BLE HID chỉ thực thi được hotkey, sequence, text và action hệ
thống được firmware hỗ trợ.

## Kiểm thử

```powershell
cd desktop
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q
uv run ruff check macropad tests
```

