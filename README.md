# WiFi Guardian – Smart Router Manager

Ứng dụng desktop Windows giám sát mạng gia đình bằng dữ liệu thật từ máy tính. Dự án chạy trực tiếp trong terminal bằng Python 3.12, **không cần build EXE** và **không tự khởi động cùng Windows**.

## Tính năng hiện có

- Dashboard dark mode với lưu lượng upload/download theo thời gian thực.
- Chọn adapter/gateway theo route thật, tránh lấy nhầm VPN hoặc VirtualBox.
- Đọc IPv4/IPv6, SSID, BSSID, tín hiệu, kênh, DNS và tốc độ liên kết khi Windows cung cấp.
- Đo ping, jitter và packet loss ở worker nền để giao diện không treo.
- Lưu mẫu lưu lượng, thiết bị và audit log vào SQLite cục bộ (`data/wifi_guardian.db`).
- Biểu đồ lịch sử 1 giờ, 6 giờ, 24 giờ hoặc 7 ngày với thống kê trung bình/cao nhất.
- Xuất lịch sử đã chọn thành CSV UTF-8 để làm báo cáo.
- Quét đúng dải LAN riêng bằng ping + bảng ARP tích hợp của Windows sau khi xác nhận.
- Tìm kiếm, lưu lịch sử và đặt tên riêng cho thiết bị.
- Sơ đồ topology có kéo, phóng to/thu nhỏ và chọn thiết bị để xem chi tiết.
- Phát hiện cổng HTTPS/HTTP của gateway LAN và mở đúng URL quản trị bằng trình duyệt.
- Cảnh báo thật khi ping mất/phục hồi, độ trễ vượt ngưỡng hoặc có thiết bị mới.
- Cài đặt chu kỳ, ping target, timeout, retention và quy tắc cảnh báo được lưu giữa các lần chạy.
- Nhật ký an toàn và cảnh báo có thể xem trực tiếp trong ứng dụng.

## Giới hạn an toàn

- Số liệu traffic là của máy tính đang chạy ứng dụng, không phải toàn bộ router.
- Không có dữ liệu giả. Trường không đọc được sẽ hiển thị “Không khả dụng”.
- Không cung cấp đổi Wi‑Fi, chặn client hoặc guest network vì không có model/firmware/API router cụ thể đã kiểm thử.
- Không phản hồi ICMP chỉ được hiển thị là “ICMP không phản hồi”, không khẳng định mất Internet.
- “Không phản hồi” không được coi là bằng chứng chắc chắn thiết bị offline.
- Quét LAN không dùng Scapy/Npcap và không quét Internet công cộng.
- Một số máy Windows yêu cầu chạy terminal bằng quyền Administrator để `netsh` trả về chi tiết Wi‑Fi; các dữ liệu khác vẫn hoạt động.
- Ứng dụng không tự chạy nền sau khi đóng cửa sổ.

## Cài đặt trong terminal

Mở PowerShell tại thư mục dự án:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Chạy ứng dụng

Chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe main.py
```

Hoặc dùng script kiểm tra `.venv`:

```powershell
.\scripts\run.ps1
```

Đóng cửa sổ là dừng ứng dụng. Không có service, scheduled task hay startup entry nào được tạo.

## Chạy kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Kiểm tra cú pháp mà không mở UI:

```powershell
.\.venv\Scripts\python.exe -m compileall -q main.py wifi_guardian tests
```

## Cấu trúc chính

```text
main.py                         Điểm chạy từ terminal
wifi_guardian/core/             Thu thập mạng và quét LAN
wifi_guardian/router/           Interface và adapter router an toàn
wifi_guardian/ui/               Giao diện, worker và theme
wifi_guardian/database.py       SQLite/SQLAlchemy
tests/                          Unit test không cần mở UI
scripts/run.ps1                 Script chạy terminal (không build)
```

## Phạm vi router

Ứng dụng hiện chỉ kiểm tra cổng quản trị của địa chỉ trong LAN và mở URL chính thức. Các adapter Omada/OpenWrt/Asus rỗng đã được loại bỏ. Muốn thêm thao tác quản trị phải có vendor, model, firmware, tài liệu API chính thức và phần cứng để kiểm thử; không đoán endpoint.

