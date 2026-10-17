# Kịch bản trình bày

Các bước dưới đây bắt đầu từ lần chạy mới, chưa có `khachsan_data.json`.
Nếu đang có dữ liệu cần giữ, sao lưu file đó trước; không xóa dữ liệu đang dùng.

## 1. Luồng cơ bản theo đề

Chạy `python main.py`.

1. Chọn **2** để thêm phòng thường: mã `S101`, tên `Standard 101`, giá `500000`,
   loại `1`.
2. Chọn **2** để thêm phòng VIP: mã `V201`, tên `VIP 201`, giá `1000000`, loại
   `2`, phí vệ sinh `150000`, phí minibar `250000`.
3. Chọn **1**: hai phòng đều ở trạng thái **Trống**.
4. Chọn **3** để đặt `S101`: mã khách `C001`, tên `Nguyen Minh An`, giấy tờ demo
   `DEMO-ID-001`, số ngày `2`.
5. Chọn **1**: `S101` chuyển sang **Đã thuê**.
6. Chọn **4**, nhập `S101`: biên nhận có tổng tiền `1,000,000.00 VND`.
7. Chọn **5**: doanh thu `1,000,000.00 VND`, phòng trống `2/2`.
8. Chọn **6**, mở lại chương trình và chọn **5**: báo cáo giữ nguyên.

Để chứng minh đa hình, đặt `V201` hai ngày rồi trả phòng. Tiền phòng VIP là
`1,000,000 × 2 + 150,000 + 250,000 = 2,400,000 VND`.

## 2. Luồng nâng cao trên desktop

Chạy `python gui.py`. Dùng hai phòng đã tạo ở trên và bảo đảm cả hai đang trống.

1. Chọn `S101` trong **Danh sách phòng**, nhấn **Đặt phòng đã chọn**. Nhập khách
   demo và số ngày `3`. Giá ban đầu là `1,500,000 VND`.
2. Sang **Khách đang ở**, chọn `S101`, nhấn **Nhận cọc**, nhập `300000`.
3. Chọn lại `S101`, nhấn **Chuyển phòng**: phòng đích `V201`, ngày đã ở phòng
   hiện tại `1`, nhân viên `front_desk`, lý do `Bao tri dieu hoa`.
4. Phiếu thuê mới gồm một ngày `S101` (`500000`) và hai ngày `V201`
   (`2000000 + 150000 + 250000`). Tổng tiền phòng là **2,900,000 VND**.
5. Chọn `V201`, nhấn **Trả phòng**, nhập bồi thường `100000` và lý do
   `Hu hong den ban`.
6. Màn hình đối soát phải hiển thị:

| Nội dung | Giá trị |
| --- | ---: |
| Tiền phòng | 2,900,000 VND |
| Cọc đã nhận | 300,000 VND |
| Bồi thường trừ cọc | 100,000 VND |
| Cọc hoàn lại | 200,000 VND |
| Thu tiền phòng khi trả phòng | 2,900,000 VND |
| Doanh thu của lượt này | 3,000,000 VND |

Chọn **No/Không** trước để chứng minh thao tác hủy giữ nguyên phiếu thuê.
Sau đó xác nhận lại. Cả hai phòng trở về **Trống**; lịch sử có biên nhận, lý do
bồi thường và nhật ký chuyển phòng. Nếu đã chạy phần 1, tổng doanh thu dashboard
còn bao gồm các lượt trả phòng trước đó.

## 3. Các tình huống nhập sai

- Nhập chữ vào giá hoặc số ngày: hiển thị lỗi và cho nhập lại.
- Thêm mã phòng trùng: bị từ chối, danh sách không phát sinh bản ghi mới.
- Đặt phòng không tồn tại hoặc đang thuê: bị từ chối.
- Nhập số ngày `0` hoặc âm: bị từ chối.
- Nhận cọc lần hai: bị từ chối.
- Trừ cọc nhiều hơn tiền đã nhận hoặc không có lý do: bị từ chối.
- Chuyển sang phòng đang thuê hoặc dùng hết số ngày ở phòng nguồn: bị từ chối.

## 4. Chạy kiểm thử tự động

```text
python -m unittest discover -s tests -v
```

Test hồi quy còn mô phỏng ổ đĩa đầy, thiếu quyền ghi, backup thất bại và thử lại
sau lỗi. Các test dùng thư mục tạm và không thao tác lên file dữ liệu đang dùng.
