# timewo-macropad

Firmware và ứng dụng cấu hình cho macropad 4 nút dùng ESP32-C3.

## Thành phần

- `src/`, `include/`: firmware PlatformIO cho ESP32-C3.
- `desktop/`: ứng dụng PySide6 cấu hình profile và nhận nút qua USB Serial/BLE GATT.
- `Mo-Macropad.cmd`: chạy bản desktop đã build.

## Chạy desktop app

```powershell
cd desktop
uv sync --locked
uv run python main.py
```

Để build một file EXE Windows:

```powershell
cd desktop
./build.ps1
```

Kết quả: `desktop/dist/v0.10-single/timewo-macropad-v0.10.0-windows-x64.exe`.
`Mo-Macropad.cmd` mở bản này; không cần cài Python trên máy sử dụng EXE.

## Nạp firmware

```powershell
pio run -t upload
```

USB của ESP32-C3 trong project này là Serial, không phải bàn phím USB HID.
Firmware mới mặc định ở chế độ Tự động; các gán nút trong NVS được giữ lại khi nạp.

## Cách dùng USB và Bluetooth

1. Đóng app cũ và Serial Monitor. Mở EXE mới, chọn cổng USB của board rồi bấm
   `Kết nối`. App đọc địa chỉ Bluetooth từ chính board để tránh chọn nhầm thiết bị.
2. Bấm `Bluetooth` để kết nối app với board. Nếu radio đang tắt và USB đã kết nối,
   thao tác này bật radio. Chấp nhận yêu cầu ghép đôi của Windows nếu xuất hiện.
3. Gán nút, bấm `Lưu cấu hình`, bỏ chọn `Chỉ kiểm tra nút`, rồi bấm `Bật macro`.
   Chuyển sang ứng dụng đích hoặc ẩn app xuống khay; macro không chạy khi cửa sổ
   cấu hình đang có focus.
4. App nhận nút qua cả hai đường, dùng ID sự kiện để chỉ chạy một lần. Khi mất
   kết nối, app nối lại và chỉ khôi phục macro nếu trước đó bạn đã bật. Tạm dừng
   hoặc sửa cấu hình sẽ hủy ý định tự khôi phục.

Giữ **nút 4 khoảng 2,5 giây** để bật/tắt radio Bluetooth trên board, không reboot.
Nhấn ngắn nút 4 chạy macro khi thả nút. Bỏ chọn nút `Bluetooth` trên app chỉ ngắt
kết nối của app, không tắt radio hay bàn phím HID của hệ điều hành.

Ví dụ: gán `Mở ứng dụng` với `C:\Program Files\Cockpit Tools\cockpit-tools.exe`.
App gọi thẳng EXE qua hệ điều hành, không gõ đường dẫn vào Run nên không
bị Telex biến đổi. `Văn bản` dán Unicode bằng clipboard và Ctrl+V; thao tác này
thay nội dung clipboard và cần ứng dụng đích hỗ trợ dán. Xuống dòng trong văn bản
là dữ liệu được dán, không phải thao tác nhấn Enter riêng.

### Dùng không cần app, trên máy bất kỳ

Mỗi lần `Lưu cấu hình` (và mỗi lần app vừa kết nối board), app tự chép profile
vào flash của board. Board nhớ profile sau khi rút điện.

Ai chạy macro được quyết định tự động:
- App đang mở và kết nối board (USB hoặc Bluetooth): app gửi lệnh `APP` mỗi giây,
  board chỉ báo nút cho app và không tự gõ, nên không có chuyện chạy hai lần.
- Tắt app, app mất kết nối, hoặc board đang ghép với máy khác: sau tối đa 3 giây
  không nhận `APP`, board tự gõ phím tắt qua Bluetooth HID. Tắt app đúng cách
  (`Ngắt kết nối`/`Thoát`) thì board nhận lại ngay.

Ví dụ: lưu `BTN1 = Ctrl+C` trên máy A, mang board sang máy B, ghép Bluetooth
`timewo-macropad` như bàn phím thường; nhấn nút 1 trên máy B là copy.

Board chỉ tự gõ được phím tắt, chuỗi phím, khóa màn hình, đóng app, chụp màn hình
(PrintScreen) và phím media. Mở app, URL và văn bản cần app đang mở. Board là
bàn phím Bluetooth: không có Bluetooth thì USB một mình không gõ được phím.

`Tùy chọn → Chế độ board → Luôn để board gõ phím` buộc board tự gõ kể cả khi app
đang mở; app khi đó không chạy macro. Thường để `Tự động` là đủ.

Nút đang bị giữ lúc board khởi động được bỏ qua cho đến khi nhả ra, nên nút kẹt
không thể tự chạy macro hay bật/tắt Bluetooth.

App phải chạy nền và phiên desktop phải mở khóa để xử lý mở app, URL và văn bản.
Không dùng profile văn bản để lưu mật khẩu máy. Trên Linux, phần bàn phím và
clipboard còn phụ thuộc desktop/X11/Wayland; khóa màn hình hiện chỉ hỗ trợ Windows.

## Các module chính

```text
src/
  button_scanner.cpp   Quét nút, debounce, phân biệt nhấn ngắn/giữ
  ble_bridge.cpp       GATT sự kiện/lệnh, dùng chung server với BLE HID
  ble_controller.cpp   Board tự gõ phím khi không có app
  usb_protocol.cpp     Phân tích lệnh USB và GATT
  profile_store.cpp    Lưu gán nút và mode trong NVS
desktop/macropad/
  bridge_protocol.py   Gói sự kiện và chống trùng USB/BLE
  ble_transport.py     Worker Bluetooth, timeout và tự nối lại
  bridge_ui.py        Điều khiển kết nối và mode trong giao diện
  transport.py        USB Serial và nhận diện đúng board
  actions.py          Mở app/web, clipboard, phím tắt trên máy
```

Sự kiện BLE là 10 byte little-endian `<BBII>`: phiên bản, nút, ID lần khởi động,
số thứ tự. USB gửi cùng ID dưới dạng `EVT <session> <sequence> <button>`.
App bỏ sự kiện trùng/cũ, không phát lại macro bị bỏ qua trong lúc tạm dừng.
Kết nối BLE sử dụng pairing/encryption; việc ghi lệnh thành công không đồng nghĩa
đã xác nhận lưu profile. Log hiện ghi `Đã gửi`, không tuyên bố đã lưu khi chưa có ACK.

## Xử lý lỗi

- `Bluetooth trên board đang tắt`: giữ nút 4 hoặc kết nối USB rồi bật nút Bluetooth.
- Không thấy board khi tìm qua BLE: thiết lập lần đầu qua USB, bật Bluetooth trên
  Windows, kiểm tra board không đang bị máy khác giữ kết nối.
- Firmware mới có thêm GATT service. Nếu Windows vẫn dùng cache cũ và báo thiếu
  service, bạn có thể xóa ghép đôi của riêng `timewo-macropad` rồi ghép lại.
- Ghép đôi thất bại (`Could not pair`, lỗi xác thực/mã hóa): app tự gỡ ghép đôi
  Windows của riêng `timewo-macropad` và ghép lại ở lần thử sau; board cũng tự bỏ
  bond hỏng của máy đó. Nếu vẫn lỗi, **giữ nút 1 trong lúc cắm điện** để board xóa
  mọi ghép đôi đã lưu, rồi xóa `timewo-macropad` trong Windows Settings và ghép lại.
- Mở COM thất bại: đóng Serial Monitor hoặc app cũ đang chiếm cổng.
- Xem `Tùy chọn → Hiện nhật ký`; profile và log nằm trong
  `%LOCALAPPDATA%\Macropad\MacropadConfigurator`.
- Rút cáp nguồn làm board tắt hẳn. BLE chỉ tiếp tục khi board còn được cấp nguồn;
  chuyển sang sạc dự phòng có thể gây một lần khởi động lại.

## Kiểm thử

Bản 0.10.0 hiện là bản kiểm thử tích hợp, chưa phải release ổn định. Các tests
tự động bao gồm chống thực thi trùng, pause/reconnect, đổi mode và clipboard.
Đã thử GATT trên board thật cùng USB, nhưng cần thử lại đủ 4 nút, tiếng Việt
trong ứng dụng đích và nhiều lần rút/cắm nguồn trước khi phát hành.

Chưa triển khai cửa sổ ghép đôi có thời hạn/allowlist và chưa có ACK xác nhận
lưu profile vào NVS qua BLE. Không suy ra tốc độ reconnect cố định từ vài lượt đo.

```powershell
cd desktop
$env:QT_QPA_PLATFORM = "offscreen"
uv run pytest -q
uv run ruff check macropad tests
```

