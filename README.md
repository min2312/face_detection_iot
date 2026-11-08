# 🔐 HỆ THỐNG SMART LOCKER IOT (TỦ ĐỒ THÔNG MINH)

Hệ thống điều khiển mở khóa tủ đồ thông minh qua nhận diện khuôn mặt kết hợp **Chống giả mạo (Face Anti-Spoofing / Liveness Detection)**, cảm biến từ phát hiện đóng/mở cửa **MC-38**, và động cơ **Servo** đóng vai trò then chốt khóa điện tử.

Hệ thống được thiết kế tối ưu để chạy trực tiếp trên **Raspberry Pi** (Pi 3B+, 4B, 5), đồng thời có chế độ **Mô phỏng (Simulation)** tự động kích hoạt khi chạy trên PC/Laptop để tiện phát triển và test demo.

---

## 📌 1. NGUYÊN LÝ HOẠT ĐỘNG & KHÓA LIÊN ĐỘNG AN TOÀN (SAFETY INTERLOCK)

* **Cảm biến từ MC-38**: Đóng vai trò **cảm biến phát hiện hành trình cánh tủ** (Cửa đang khép chặt hay đang mở).
* **Động cơ Servo**: Đóng vai trò **then chốt / ổ khóa cơ điện tử** (Góc 0° = Khóa chốt, Góc 90° = Mở chốt).
* **Quy tắc an toàn cơ khí (Safety Interlock)**:
  1. Khi người dùng xác thực thành công $\rightarrow$ Servo quay mở chốt khóa (90°).
  2. Người dùng kéo cửa tủ ra $\rightarrow$ Cảm biến từ MC-38 hở mạch $\rightarrow$ Web báo *"Cửa đang mở"*.
  3. **Trong lúc cửa đang mở, Servo BẮT BUỘC GIỮ NGUYÊN trạng thái mở**, tuyệt đối không tự hạ chốt xuống để tránh làm gãy chốt khi người dùng đẩy cánh cửa vào.
  4. Chỉ khi người dùng bỏ/lấy đồ xong và **khép chặt cánh cửa vào** $\rightarrow$ MC-38 đóng mạch $\rightarrow$ Servo mới kích hoạt **hạ chốt xuống 0° để khóa lại**.

---

## 🔌 2. SƠ ĐỒ ĐẤU DÂY TRÊN RASPBERRY PI (WIRING DIAGRAM)

| Thiết bị | Chân thiết bị | Chân Raspberry Pi | Số hiệu chân vật lý (Header Pin) | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **Động cơ Servo (SG90 / MG995)** | Dây Đỏ (VCC) | **5V Power** | Pin 2 hoặc Pin 4 | Nên cấp nguồn 5V riêng nếu dùng servo lớn |
| | Dây Nâu / Đen (GND) | **Ground** | Pin 6 | Nối chung GND với Pi |
| | Dây Cam / Vàng (Signal) | **GPIO 18 (PWM)** | Pin 12 | Điều khiển góc mở 0° - 90° |
| **Cảm biến từ MC-38** | Dây 1 | **GPIO 23** | Pin 16 | Cấu hình kéo nội `pull_up=True` |
| | Dây 2 | **Ground** | Pin 14 | Khi cửa đóng: tiếp xúc GND $\rightarrow$ mức 0 |
| **Đèn LED Đỏ (Cảnh báo Fake/Lỗi)** | Cực Dương (+) | **GPIO 17** | Pin 11 | Nối qua điện trở 220Ω - 330Ω |
| | Cực Âm (-) | **Ground** | Pin 9 | |
| **Đèn LED Xanh (Thành công/Mở)** | Cực Dương (+) | **GPIO 27** | Pin 13 | Nối qua điện trở 220Ω |
| | Cực Âm (-) | **Ground** | Pin 20 | |
| **Camera USB** | Cổng USB | Cổng USB 2.0 / 3.0 | Bất kỳ cổng USB nào | Tự động nhận dạng qua V4L2 |

> [!TIP]
> Cảm biến từ MC-38 là công tắc tiếp điểm từ (Reed switch). Một nửa gắn cố định trên khung tủ, một nửa chứa nam châm gắn trên cánh cửa. Khi 2 miếng sát nhau (khoảng cách < 1.5 cm) là CỬA ĐÓNG.

---

## 🚀 3. HƯỚNG DẪN CÀI ĐẶT TRÊN RASPBERRY PI

### Bước 1: Sao chép thư mục `ck_iot` sang Raspberry Pi
Bạn có thể copy thư mục `ck_iot` sang thẻ nhớ Raspberry Pi hoặc clone qua Git/SCP.

### Bước 2: Cấp quyền và chạy script cài đặt tự động
Mở terminal trên Raspberry Pi và chạy:
```bash
cd ck_iot
chmod +x install.sh run.sh download_models.sh
./install.sh
```

Script `install.sh` sẽ tự động:
1. Cài các gói hệ thống Linux cần thiết (`libgl1`, `v4l-utils`, `curl`).
2. Tạo môi trường ảo `.venv` chuẩn PEP 668 của Debian/Pi OS.
3. Cài các thư viện Python: `Flask`, `OpenCV`, `NumPy`, `gpiozero`, `lgpio`.
4. Tải 3 model AI:
   - `face_detection_yunet_2023mar.onnx` (Phát hiện mặt)
   - `face_recognition_sface_2021dec.onnx` (Nhận diện mặt)
   - `MiniFASNetV2.onnx` (Chống giả mạo liveness / anti-spoofing)

### Bước 3: Khởi chạy hệ thống
```bash
./run.sh
```

Mở trình duyệt trên điện thoại hoặc máy tính trong cùng mạng LAN:
* **Giao diện Kiosk Người dùng**: `http://<IP_RASPBERRY_PI>:5000`
* **Giao diện Quản trị Admin**: `http://<IP_RASPBERRY_PI>:5000/admin`
*(Tài khoản admin mặc định: `admin` / `admin123`)*

---

## 💻 4. CHẠY VÀ TEST THỬ TRÊN MÁY TÍNH (PC / WINDOWS / MAC)

Nếu bạn chưa cắm Raspberry Pi và muốn chạy thử trước trên Laptop/PC:
```bash
# Trong môi trường Python
pip install -r requirements.txt
python download_models.py
python app.py
```
* Hệ thống sẽ tự phát hiện đang chạy ngoài Raspberry Pi và tự động kích hoạt **Chế độ Mô phỏng (Simulation)**.
* Trên giao diện web sẽ có sẵn bảng nút:
  - `🚪 Giả lập Mở Cửa (Hở từ)`
  - `🚪 Giả lập Đóng Cửa (Chạm từ)`
  Giúp bạn test hoàn chỉnh quy trình Cất đồ, Lấy đồ, và Khóa an toàn trước khi nối dây mạch thật!

---

## 🎯 5. KỊCH BẢN DEMO ĐỒ ÁN

1. **Test Chống Giả Mạo (Anti-Spoofing)**:
   - Bấm **CẤT ĐỒ**.
   - Đưa màn hình điện thoại có ảnh chụp khuôn mặt trước camera $\rightarrow$ Hệ thống hiện viền đỏ **🚨 SPOOF (SPOOF_SCREEN)** và từ chối mở cửa.
   - Đưa mặt người thật vào $\rightarrow$ Hệ thống báo **👤 Người thật**, lưu dữ liệu và mở khóa Servo ngay lập tức.
2. **Test Khóa Liên Động Cửa (MC-38 + Servo)**:
   - Sau khi mở servo, kéo mở cửa tủ ra $\rightarrow$ Web lập tức hiển thị **CỬA ĐANG MỞ** màu đỏ, Servo giữ nguyên vị trí mở.
   - Người dùng bỏ đồ vào tủ, sau đó khép cửa tủ lại $\rightarrow$ Cảm biến từ MC-38 tiếp xúc $\rightarrow$ Servo lập tức hạ chốt xuống khóa lại, chuyển trạng thái tủ sang **ĐANG CÓ ĐỒ**.
3. **Test Lấy Đồ**:
   - Bấm **QUÉT MẶT LẤY ĐỒ**.
   - Nếu người khác đứng vào $\rightarrow$ Hệ thống báo **❌ Sai khuôn mặt**, không mở.
   - Đúng người đã gửi cất đồ đứng vào $\rightarrow$ Hệ thống xác thực thành công, mở chốt servo cho lấy đồ, sau khi đóng cửa lại thì giải phóng tủ về trạng thái **TRỐNG (AVAILABLE)**.
4. **Test Quản trị Admin**:
   - Truy cập `/admin` để xem danh sách lịch sử đóng/mở tủ, ảnh chụp người gửi, các lần phát hiện ảnh giả mạo, và nút **Mở khóa khẩn cấp**.

