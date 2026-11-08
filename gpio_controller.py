"""
gpio_controller.py - Điều khiển 4 Servo qua Module PCA9685 (I2C) & 4 Cảm biến từ MC-38 (GPIO)
Hỗ trợ cả môi trường Raspberry Pi thực tế và Chế độ Mô phỏng (Simulation) trên PC.
"""

import os
import sys
import threading
import time
from typing import Callable, Dict, Optional

# Kiểm tra thư viện trên Linux / Raspberry Pi
USE_REAL_GPIO = False
HAS_SMBUS = False
HAS_SERVOKIT = False

if sys.platform.startswith("linux"):
    try:
        from gpiozero import Button, LED
        USE_REAL_GPIO = True
    except (ImportError, RuntimeError):
        USE_REAL_GPIO = False

    try:
        from adafruit_servokit import ServoKit
        HAS_SERVOKIT = True
    except ImportError:
        HAS_SERVOKIT = False

    try:
        import smbus2 as smbus
        HAS_SMBUS = True
    except ImportError:
        try:
            import smbus
            HAS_SMBUS = True
        except ImportError:
            HAS_SMBUS = False


# ── DRIVER I2C CHO MODULE PCA9685 (HỖ TRỢ CẢ SERVOKIT & NATIVE SMBUS) ────────────

class PCA9685Driver:
    """Điều khiển PCA9685 qua adafruit_servokit HOẶC native smbus2 I2C."""
    MODE1 = 0x00
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, bus_num: int = 1, address: int = 0x40):
        self.address = address
        self.kit = None
        self.bus = None

        # 1. Thử dùng adafruit_servokit nếu có cài sẵn
        if HAS_SERVOKIT:
            try:
                self.kit = ServoKit(channels=16, address=address)
                print(f"✅ [PCA9685] Đã kết nối qua thư viện Adafruit ServoKit (Địa chỉ 0x{address:02X})")
                return
            except Exception as e:
                print(f"⚠️ [PCA9685] Thử ServoKit không thành công ({e}), chuyển sang Native I2C smbus...")
                self.kit = None

        # 2. Dùng Driver Native I2C qua smbus2 (nhẹ, nhanh, không cần thư viện cồng kềnh)
        if HAS_SMBUS:
            try:
                self.bus = smbus.SMBus(bus_num)
                self._init_pca9685()
                print(f"✅ [PCA9685] Đã kết nối module qua Native I2C smbus Bus {bus_num} (Địa chỉ 0x{address:02X})")
            except Exception as e:
                print(f"⚠️ [PCA9685 Warning] Không thể mở I2C: {e}. Sẽ dùng mô phỏng.")
                self.bus = None

    def _init_pca9685(self):
        """Khởi tạo tần số 50Hz chuẩn cho Servo (khi chạy qua smbus native)."""
        if not self.bus:
            return
        # Sleep mode để set prescale
        self.bus.write_byte_data(self.address, self.MODE1, 0x10)
        # Prescale cho 50Hz = round(25000000 / (4096 * 50)) - 1 = 121 (0x79)
        self.bus.write_byte_data(self.address, self.PRESCALE, 0x79)
        # Bật lại và cho phép Auto-Increment
        self.bus.write_byte_data(self.address, self.MODE1, 0xA1)
        time.sleep(0.005)

    def set_servo_angle(self, channel: int, angle: float):
        """
        Quay servo ở kênh `channel` (0-15) tới góc `angle` (0° đến 180°).
        - 0°: Then khóa hạ xuống
        - 90°: Mở chốt
        """
        # Nếu đang dùng Adafruit ServoKit
        if self.kit is not None:
            try:
                self.kit.servo[channel].angle = max(0, min(180, int(angle)))
            except Exception as e:
                print(f"❌ [ServoKit Error] Lỗi quay Servo kênh {channel}: {e}")
            return

        # Nếu đang dùng Driver Native smbus2
        if not self.bus:
            return

        # Tính toán giá trị PWM (0 - 4095) tương ứng với 0° - 180°
        # 0.5ms (pulse 102) -> 2.5ms (pulse 512)
        pulse = int(102 + (angle / 180.0) * (512 - 102))
        pulse = max(100, min(520, pulse))

        reg = self.LED0_ON_L + 4 * channel
        try:
            self.bus.write_byte_data(self.address, reg, 0)
            self.bus.write_byte_data(self.address, reg + 1, 0)
            self.bus.write_byte_data(self.address, reg + 2, pulse & 0xFF)
            self.bus.write_byte_data(self.address, reg + 3, pulse >> 8)
        except Exception as e:
            print(f"❌ [PCA9685 Error] Lỗi quay Servo kênh {channel}: {e}")


# ── BỘ ĐIỀU KHIỂN PHẦN CỨNG 4 NGĂN TỦ ───────────────────────────────

class HardwareController:
    """
    Quản lý 4 Servo qua PCA9685 (Kênh 0..3) và 4 Cảm biến từ MC-38 (GPIO 23, 24, 25, 26).
    """

    def __init__(
        self,
        pca_bus: int = 1,
        pca_addr: int = 0x40,
        door_pins: Dict[int, int] = None,
        red_led_pin: int = 17,
        green_led_pin: int = 27,
    ):
        # Mặc định 4 chân GPIO cho 4 cảm biến từ MC-38
        if door_pins is None:
            self.door_pins = {
                1: int(os.environ.get("DOOR_1_PIN", "23")),
                2: int(os.environ.get("DOOR_2_PIN", "24")),
                3: int(os.environ.get("DOOR_3_PIN", "25")),
                4: int(os.environ.get("DOOR_4_PIN", "26")),
            }
        else:
            self.door_pins = door_pins

        # Kênh PCA9685 cho 4 Servo (Có thể cắm vào bất kỳ kênh nào 0-15 và chỉnh trong .env)
        self.servo_channels = {
            1: int(os.environ.get("SERVO_1_CHANNEL", "0")),
            2: int(os.environ.get("SERVO_2_CHANNEL", "1")),
            3: int(os.environ.get("SERVO_3_CHANNEL", "2")),
            4: int(os.environ.get("SERVO_4_CHANNEL", "3")),
        }

        # Trạng thái 4 ngăn tủ
        self.lock_states: Dict[int, str] = {i: "LOCKED" for i in range(1, 5)}
        self.door_states: Dict[int, str] = {i: "CLOSED" for i in range(1, 5)}

        # Bộ đếm delay 1s trước khi khóa cửa cho từng tủ
        self._close_timers: Dict[int, Optional[threading.Timer]] = {i: None for i in range(1, 5)}

        self.on_door_state_change: Optional[Callable[[int, str], None]] = None
        self._lock = threading.Lock()

        # Kiểm tra chế độ phần cứng thật
        self.is_real_hardware = USE_REAL_GPIO and (os.environ.get("MOCK_GPIO", "0") != "1")
        self.pca = PCA9685Driver(bus_num=pca_bus, address=pca_addr) if self.is_real_hardware else None

        self.red_led = None
        self.green_led = None
        self.sensor_buttons = {}

        if self.is_real_hardware:
            self._init_real_hardware(red_led_pin, green_led_pin)
        else:
            print("💡 [GPIO Simulation] Chế độ mô phỏng 4 Tủ (PCA9685 & MC-38) đang hoạt động trên PC.")

    def _init_real_hardware(self, red_pin: int, green_pin: int):
        """Khởi tạo chân GPIO trên Raspberry Pi."""
        try:
            # 1. Khởi tạo 4 cảm biến từ MC-38
            for locker_id, pin in self.door_pins.items():
                btn = Button(pin, pull_up=True, bounce_time=0.1)
                
                # Tạo closure gắn đúng locker_id
                def make_pressed(lid):
                    return lambda: self._handle_door_event(lid, "CLOSED")
                def make_released(lid):
                    return lambda: self._handle_door_event(lid, "OPEN")

                btn.when_pressed = make_pressed(locker_id)
                btn.when_released = make_released(locker_id)
                self.sensor_buttons[locker_id] = btn

                # Đọc trạng thái ban đầu
                self.door_states[locker_id] = "CLOSED" if btn.is_pressed else "OPEN"

            # 2. Đèn báo LED
            self.red_led = LED(red_pin)
            self.green_led = LED(green_pin)
            self.red_led.off()
            self.green_led.off()

            # 3. Khóa tất cả 4 Servo về góc 0°
            for i in range(1, 5):
                self.lock_locker(i, force=True)

            print(f"✅ [GPIO] Đã kích hoạt 4 Cảm biến từ MC-38 trên GPIO: {self.door_pins}")
        except Exception as e:
            print(f"⚠️ [GPIO Error] Lỗi khởi tạo GPIO: {e}")
            self.is_real_hardware = False

    def _handle_door_event(self, locker_id: int, new_state: str):
        """Xử lý sự kiện mở/đóng cửa cho từng tủ."""
        with self._lock:
            old_state = self.door_states.get(locker_id, "CLOSED")
            if old_state == new_state:
                return
            self.door_states[locker_id] = new_state
            print(f"🧲 [MC-38 Tủ {locker_id}] Cảm biến phát hiện: CỬA {new_state}!", flush=True)

            # Nếu cửa vừa MỞ ra: Hủy bất kỳ lệnh hẹn giờ khóa nào đang chờ
            if new_state == "OPEN":
                timer = self._close_timers.get(locker_id)
                if timer and timer.is_alive():
                    timer.cancel()
                    self._close_timers[locker_id] = None

        if callable(self.on_door_state_change):
            try:
                self.on_door_state_change(locker_id, new_state)
            except Exception as e:
                print(f"[Error callback door {locker_id}]: {e}")

    # ── ĐIỀU KHIỂN KHÓA SERVO (TỨC THÌ 0 DELAY KHI MỞ) ──────────────────

    def unlock_locker(self, locker_id: int) -> bool:
        """
        MỞ KHÓA TỨC THÌ (0 DELAY):
        Quay Servo kênh tương ứng lên góc 90° ngay lập tức, không dùng bất kỳ sleep nào.
        """
        with self._lock:
            # Hủy timer khóa nếu có
            timer = self._close_timers.get(locker_id)
            if timer and timer.is_alive():
                timer.cancel()
                self._close_timers[locker_id] = None

            self.lock_states[locker_id] = "UNLOCKED"
            ch = self.servo_channels.get(locker_id, 0)
            print(f"🔓 [SERVO Tủ {locker_id}] MỞ KHÓA TỨC THÌ (PCA9685 Kênh {ch} -> Góc 90°)", flush=True)

            if self.is_real_hardware and self.pca:
                self.pca.set_servo_angle(ch, 90.0)

            if self.green_led:
                self.green_led.on()

        return True

    def lock_locker(self, locker_id: int, force: bool = False) -> bool:
        """
        HẠ CHỐT KHÓA (Góc 0°):
        Nếu cửa đang MỞ và không ép buộc (force=False) -> TỪ CHỐI KHÓA để bảo vệ chốt servo.
        """
        with self._lock:
            if not force and self.door_states.get(locker_id) == "OPEN":
                print(f"⚠️ [SAFETY Tủ {locker_id}] Cửa đang MỞ! TỪ CHỐI hạ chốt để chống kẹt/gãy chốt.", flush=True)
                return False

            self.lock_states[locker_id] = "LOCKED"
            ch = self.servo_channels.get(locker_id, 0)
            print(f"🔒 [SERVO Tủ {locker_id}] Hạ chốt khóa an toàn (PCA9685 Kênh {ch} -> Góc 0°)", flush=True)

            if self.is_real_hardware and self.pca:
                self.pca.set_servo_angle(ch, 0.0)

        return True

    def schedule_lock_after_delay(self, locker_id: int, delay_seconds: float = 1.0, callback: Callable = None):
        """
        Hẹn giờ: Đợi đúng `delay_seconds` (mặc định 1.0s) sau khi cửa đóng hoàn toàn mới hạ chốt Servo.
        Đúng yêu cầu: 'user đóng cửa sau 1s ms đóng servo lại'.
        """
        def _worker():
            # Kiểm tra lại chắc chắn cửa vẫn đang đóng
            if self.door_states.get(locker_id) == "CLOSED":
                self.lock_locker(locker_id)
                if callable(callback):
                    callback(locker_id)

        with self._lock:
            # Hủy timer cũ nếu có
            old_timer = self._close_timers.get(locker_id)
            if old_timer and old_timer.is_alive():
                old_timer.cancel()

            print(f"⏱️ [Timer Tủ {locker_id}] Cửa đã khép kín. Đang chờ đúng {delay_seconds:.1f}s trước khi hạ chốt khóa...", flush=True)
            timer = threading.Timer(delay_seconds, _worker)
            self._close_timers[locker_id] = timer
            timer.start()

    # ── ĐÈN BÁO & CÒI CẢNH BÁO ──────────────────────────────────────────

    def flash_red(self, duration: float = 1.5):
        def _w():
            if self.red_led:
                try:
                    self.red_led.on()
                except Exception:
                    pass
            time.sleep(duration)
            if self.red_led:
                try:
                    self.red_led.off()
                except Exception:
                    pass
        threading.Thread(target=_w, daemon=True).start()

    def flash_green(self, duration: float = 1.5):
        def _w():
            if self.green_led:
                try:
                    self.green_led.on()
                except Exception:
                    pass
            time.sleep(duration)
            if self.green_led and all(s == "LOCKED" for s in self.lock_states.values()):
                try:
                    self.green_led.off()
                except Exception:
                    pass
        threading.Thread(target=_w, daemon=True).start()

    # ── MÔ PHỎNG TEST TRÊN PC ──────────────────────────────────────────

    def simulate_set_door(self, locker_id: int, state: str):
        state = state.upper()
        if state not in ("OPEN", "CLOSED"):
            return
        self._handle_door_event(locker_id, state)

    def get_status(self) -> dict:
        return {
            "lock_states": dict(self.lock_states),   # {1: "LOCKED", 2: "UNLOCKED", ...}
            "door_states": dict(self.door_states),   # {1: "CLOSED", 2: "OPEN", ...}
            "is_real_hardware": self.is_real_hardware,
            "door_pins": self.door_pins,
            "servo_channels": self.servo_channels,
        }

    def cleanup(self):
        if self.is_real_hardware:
            for btn in self.sensor_buttons.values():
                try:
                    btn.close()
                except Exception:
                    pass
            if self.red_led:
                self.red_led.close()
            if self.green_led:
                self.green_led.close()
