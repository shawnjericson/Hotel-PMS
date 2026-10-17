# Hotel PMS

Ứng dụng quản lý khách sạn bằng Python, gồm giao diện dòng lệnh (CLI) theo đề thi
và giao diện desktop bằng Tkinter. Chương trình sử dụng lập trình hướng đối tượng,
tách module, xử lý ngoại lệ và lưu dữ liệu JSON.

Tên lớp, hàm, biến và khóa JSON sử dụng tiếng Anh. Giao diện desktop hiển thị
tiếng Việt; trạng thái phòng là **Trống** và **Đã thuê**.

## Chạy nhanh

Yêu cầu **Python 3.10 trở lên**, có Tkinter. Không cần cài thư viện bằng `pip`.
Với Windows, dùng bộ cài Python chính thức có thành phần Tcl/Tk và IDLE.

```powershell
git clone https://github.com/shawnjericson/Hotel-PMS.git
cd Hotel-PMS
python main.py
```

- **CLI theo đề thi:** `python main.py` hoặc nhấp đúp `launch_cli.bat` trên Windows.
- **Giao diện desktop:** `python gui.py` hoặc nhấp đúp `launch_gui.bat` trên Windows.
- Trên macOS/Linux, có thể dùng lệnh `python3` thay cho `python`.

Lần chạy đầu tiên bắt đầu với danh sách phòng rỗng. Chọn **Thêm phòng**, sau đó
đặt phòng để thực hiện các bước tiếp theo. Dữ liệu tự lưu vào `khachsan_data.json`
bên cạnh mã nguồn và được nạp lại khi mở chương trình.

## Đối chiếu yêu cầu đề thi

| Yêu cầu | Cách triển khai | Module |
| --- | --- | --- |
| Lớp phòng cơ sở và hai lớp con | `Room`, `StandardRoom`, `VIPRoom` | `models.py` |
| Đóng gói trạng thái | Thuộc tính riêng, property chỉ đọc, các phương thức đổi trạng thái | `models.py` |
| Khách hàng và phiếu thuê | `Customer`, `RentalRecord`, giữ tham chiếu đối tượng phòng/khách | `models.py` |
| Kế thừa và đa hình | Hai lớp phòng định nghĩa `calculate_total()` theo quy tắc riêng | `models.py` |
| Thêm phòng, đặt phòng, trả phòng | `HotelManager` kiểm tra điều kiện và điều phối nghiệp vụ | `services.py` |
| Lưu và nạp JSON | `save_data()`, `load_data()`, lưu qua file tạm rồi thay thế | `file_handler.py` |
| Lịch sử và báo cáo doanh thu | Biên nhận bất biến, tổng doanh thu, số phòng trống | `models.py`, `services.py` |
| Menu lặp và bắt lỗi | Sáu lựa chọn chính, báo lỗi rồi quay lại menu | `main.py` |

Các phương thức tính tiền nằm cùng lớp phòng để thể hiện kế thừa và đa hình.
`services.py` sử dụng giá đã chốt của từng phân đoạn lưu trú khi trả phòng.

## Menu CLI

```text
1. Display rooms
2. Add a room
3. Book a room
4. Check out and pay
5. View revenue report
6. Save and exit
7. Record a security deposit
8. Transfer an active rental
9. Settle deposit/damage and check out
```

Các mục **1–6** đáp ứng luồng chính của đề. Các mục **7–9** và giao diện desktop
là phần mở rộng, dùng chung lớp nghiệp vụ.

## Quy tắc tính tiền

- Phòng thường: `giá mỗi ngày × số ngày thuê`.
- Phòng VIP: `giá mỗi ngày × số ngày thuê + phí vệ sinh + phí minibar`.
- Phí VIP tính một lần cho mỗi lượt ở một phòng; khi chuyển phòng, mỗi phân đoạn
  có bộ giá/phí riêng. Đây là quy ước được ghi rõ vì đề không quy định chu kỳ phí.
- Tiền sử dụng `Decimal`, lưu dưới dạng chuỗi trong JSON để tránh sai số `float`.
- Số ngày phải là số nguyên dương. Tiền không được âm; mã phòng không được trùng.

## Nghiệp vụ mở rộng

**Chốt giá và giữ lịch sử:** mỗi lượt đặt/chuyển phòng có một bản chụp giá, tên
và loại phòng. Thay đổi danh mục sau đó không tính lại tiền của phân đoạn đã chốt.
Biên nhận trả phòng và các dòng lịch sử dùng dataclass bất biến.

**Cọc bảo đảm và đối soát:** cọc được ghi nhận một lần, tách khỏi tiền phòng và
doanh thu. Khi trả phòng, chương trình thu đủ tiền phòng và hoàn cọc sau khi trừ
bồi thường. Khoản trừ phải có lý do và không vượt tiền cọc; lý do được giữ trong
lịch sử và biên nhận. Cọc này là cọc bảo đảm, không phải tiền phòng trả trước.

```text
Cọc đã nhận + Tiền thu khi trả phòng − Cọc hoàn lại
    = Tiền phòng + Bồi thường
    = Doanh thu ghi nhận
```

**Chuyển phòng:** chỉ chuyển sang phòng trống, phải còn ít nhất một ngày ở phòng
đích. Phiếu thuê, khách và tiền cọc được giữ nguyên; lịch sử ghi nhân viên, lý do,
phòng nguồn/đích và chênh lệch giá. Lỗi kiểm tra hoặc lưu file không thay đổi phiên
làm việc hiện tại.

**Bảo vệ khi lưu:** CLI và UI thực hiện thay đổi trên bản sao, chỉ cập nhật phiên
làm việc sau khi file đã lưu thành công. Một báo giá đối soát cũ bị từ chối nếu
phiếu thuê đã thay đổi. Nếu CLI gặp JSON lỗi, phải tạo được backup trước khi mở
phiên rỗng; nếu backup thất bại, chương trình giữ nguyên file gốc và báo lỗi.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

Bộ kiểm thử bao gồm tính tiền, trạng thái phòng, dữ liệu không hợp lệ, chốt giá,
cọc/hoàn cọc, chuyển phòng nhiều lần, lưu/mở lại JSON, lỗi ghi file, khả năng thử
lại, bảo vệ file gốc và thao tác biểu mẫu desktop. Test dùng dữ liệu tạm riêng.

Test giao diện cần Tkinter và môi trường hiển thị. Trên Linux không có desktop:

```bash
xvfb-run -a python -m unittest discover -s tests -v
```

GitHub Actions tự chạy bộ kiểm thử khi push hoặc tạo pull request.

## Cấu trúc

```text
Hotel-PMS/
├── main.py                    # CLI theo đề thi
├── gui.py                     # Giao diện desktop
├── models.py                  # Đối tượng, giá chốt và biên nhận
├── services.py                # Điều phối nghiệp vụ
├── file_handler.py            # Lưu/nạp JSON
├── launch_cli.bat             # Chạy CLI trên Windows
├── launch_gui.bat             # Chạy desktop trên Windows
├── docs/DEMO.md               # Kịch bản trình bày và kết quả mong đợi
├── tests/                     # Unit test và kiểm thử luồng giao diện
└── Đề thi cuối môn.docx        # Đề bài gốc
```

## Phạm vi

Đây là ứng dụng học phần chạy cục bộ cho một người dùng tại một thời điểm.
Chương trình chưa triển khai đặt phòng theo lịch ngày, nhiều người dùng đồng thời,
tài khoản đăng nhập hoặc kết nối thanh toán. File JSON đang dùng và các file
backup không được đưa vào Git.

Định dạng JSON hiện tại là phiên bản 2; chương trình vẫn đọc được phiên bản 1.
Lịch sử cũ chưa từng lưu lý do bồi thường sẽ được hiển thị là thiếu thông tin,
không tự tạo lý do thay thế.
