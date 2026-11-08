# 🔐 HỆ THỐNG SMART LOCKER 4 NGĂN TỦ (PCA9685 & MC-38 & AI FACE)

Hệ thống điều khiển 4 ngăn tủ thông minh độc lập:
* **Nhận diện khuôn mặt & Chống giả mạo (Anti-Spoofing)**: Sử dụng **YuNet + SFace + MiniFASNetV2**.
* **Điều khiển 4 Động cơ Servo**: Sử dụng **Module PCA9685 (I2C 16-channel PWM)** giúp tiết kiệm chân Pi, không bị rung giật (jitter) và cấp nguồn 5V riêng an toàn cho 4 servo.
* **4 Cảm biến từ phát hiện đóng/mở cửa**: Sử dụng **MC-38** trên 4 chân GPIO độc lập.
* **Nguyên tắc thời gian & Khóa liên động (Interlock)**:
  * Khi nhận diện đúng người: **Servo mở chốt TỨC THÌ (0 delay)**.
  * Khi cửa đang mở: **Servo GIỮ NGUYÊN trạng thái mở** để chống kẹt/gãy chốt.
  * Khi người dùng đóng sập cửa lại: Cảm biến từ MC-38 báo đóng $\rightarrow$ **Đếm đúng 1.0 giây để cửa ổn định hoàn toàn rồi mới hạ chốt Servo khóa lại**.

---

## 🔌 1. SƠ ĐỒ ĐẤU DÂY CHI TIẾT (RASPBERRY PI & PCA9685 & MC-38)

### A. Module PCA9685 (Điều khiển 4 Servo qua I2C)
| Chân PCA9685 | Kết nối tới | Số hiệu chân Header Raspberry Pi | Ghi chú |
| :--- | :--- | :--- | :--- |
| **VCC** | **3.3V Power** | Pin 1 | Nuôi chip PCA9685 |
| **GND** | **Ground** | Pin 9 | Nối chung mass GND |
| **SDA** | **GPIO 2 (I2C SDA)** | Pin 3 | Tín hiệu dữ liệu I2C |
| **SCL** | **GPIO 3 (I2C SCL)** | Pin 5 | Tín hiệu xung nhịp I2C |
| **V+ (Terminal xanh)** | **Nguồn ngoài 5V - 3A (+)** | Nguồn Adapter rời | **Bắt buộc dùng nguồn rời** nuôi 4 servo |
| **GND (Terminal xanh)** | **Nguồn ngoài 5V - 3A (-)** | Nguồn Adapter rời | Nối chung GND với Pi |
| **Kênh 0 (Channel 0)** | **Servo Tủ số 1** | Cắm hàng chân 3 pin kênh 0 | Vàng/Cam (PWM), Đỏ (V+), Nâu/Đen (GND) |
| **Kênh 1 (Channel 1)** | **Servo Tủ số 2** | Cắm hàng chân 3 pin kênh 1 | |
| **Kênh 2 (Channel 2)** | **Servo Tủ số 3** | Cắm hàng chân 3 pin kênh 2 | |
| **Kênh 3 (Channel 3)** | **Servo Tủ số 4** | Cắm hàng chân 3 pin kênh 3 | |

### B. 4 Cảm biến từ MC-38 (Chốt nhận diện đóng/mở cửa)
| Thiết bị | Dây tín hiệu | Chân Raspberry Pi | Chân vật lý Header | Dây còn lại |
| :--- | :--- | :--- | :--- | :--- |
| **MC-38 Tủ số 1** | Dây 1 | **GPIO 23** | Pin 16 | Nối vào **GND** (Pin 14) |
| **MC-38 Tủ số 2** | Dây 1 | **GPIO 24** | Pin 18 | Nối vào **GND** (Pin 20) |
| **MC-38 Tủ số 3** | Dây 1 | **GPIO 25** | Pin 22 | Nối vào **GND** (Pin 25) |
| **MC-38 Tủ số 4** | Dây 1 | **GPIO 26** | Pin 37 | Nối vào **GND** (Pin 39) |

### C. Đèn báo LED & Camera
* **Đèn LED Đỏ** (Báo lỗi / Fake): Chân dương vào **GPIO 17** (Pin 11) qua trở $220\Omega$, Chân âm vào **GND** (Pin 6).
* **Đèn LED Xanh** (Báo mở thành công): Chân dương vào **GPIO 27** (Pin 13) qua trở $220\Omega$, Chân âm vào **GND**.
* **Camera**: Stream từ Laptop (qua Wi-Fi) hoặc cắm USB trực tiếp vào Pi.

---

## ⚙️ 2. BẬT I2C TRÊN RASPBERRY PI

Trước khi chạy, hãy đảm bảo I2C đã được kích hoạt trên Raspberry Pi:
```bash
sudo raspi-config
# Chọn: Interface Options -> I2C -> Yes
```
Kiểm tra xem Pi đã nhận module PCA9685 chưa:
```bash
sudo i2cdetect -y 1
```
*(Nếu thấy địa chỉ `40` hoặc `70` hiện lên bảng ma trận là đã kết nối phần cứng chuẩn 100%).*

---

## 🚀 3. HƯỚNG DẪN CHẠY HỆ THỐNG

### Cập nhật và chạy trên Raspberry Pi:
```bash
git pull origin main
./run.sh
```

### Mở trình duyệt:
* **Giao diện Kiosk Người dùng (4 Tủ)**: `http://<IP_PI>:5000`
* **Giao diện Quản trị Admin**: `http://<IP_PI>:5000/admin`
*(Mặc định: `admin` / `admin123`)*
