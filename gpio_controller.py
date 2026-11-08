"""
gpio_controller.py - Quản lý tương tác phần cứng (Servo, Cảm biến từ MC-38, LED/Còi)
Hỗ trợ cả môi trường thật trên Raspberry Pi (gpiozero) và chế độ Mô phỏng (Simulation) trên PC/Windows.
"""

import os
import sys
import threading
import time
from typing import Callable, Optional

# Kiểm tra xem có đang chạy trên Linux/Raspberry Pi với gpiozero không
USE_REAL_GPIO = False
if sys.platform.startswith("linux"):
    try:
        from gpiozero import AngularServo, Button, LED
        USE_REAL_GPIO = True
    except (ImportError, RuntimeError):
        USE_REAL_GPIO = False


class HardwareController:
    """
    Điều khiển Servo (ổ khóa), Cảm biến từ MC-38 (chốt nhận diện cửa), và Đèn báo LED.
    """

    def __init__(
        self,
        servo_pin: int = 18,
        door_sensor_pin: int = 23,
        red_led_pin: int = 17,
        green_led_pin: int = 27,
        invert_door_sensor: bool = False,
    ):
        self.servo_pin = servo_pin
        self.door_sensor_pin = door_sensor_pin
        self.red_led_pin = red_led_pin
        self.green_led_pin = green_led_pin
        self.invert_door_sensor = invert_door_sensor

        # Trạng thái logic phần cứng
        # Lock status: "LOCKED" (chốt hạ - khóa) hoặc "UNLOCKED" (chốt mở)
        self.lock_state = "LOCKED"
        # Door status: "CLOSED" (cửa khép chặt) hoặc "OPEN" (cửa đang mở)
        self.door_state = "CLOSED"

        # Callbacks khi trạng thái cửa thay đổi: callback(new_state: str)
        self.on_door_state_change: Optional[Callable[[str], None]] = None
        self._lock = threading.Lock()

        self.is_real_hardware = USE_REAL_GPIO and (os.environ.get("MOCK_GPIO", "0") != "1")

        if self.is_real_hardware:
            try:
                self._init_real_gpio()
                print(f"✅ [GPIO] Đã kích hoạt phần cứng Raspberry Pi:")
                print(f"   - Servo: GPIO {servo_pin} (0°=Khóa, 90°=Mở)")
                print(f"   - Cảm biến từ MC-38: GPIO {door_sensor_pin}")
                print(f"   - Red LED: GPIO {red_led_pin} | Green LED: GPIO {green_led_pin}")
            except Exception as e:
                print(f"⚠️ [GPIO Warning] Không thể mở GPIO thật: {e}. Chuyển sang mô phỏng.")
                self.is_real_hardware = False
        else:
            print("💡 [GPIO Simulation] Đang chạy chế độ mô phỏng phần cứng (Thích hợp test trên PC/Laptop).")

    def _init_real_gpio(self):
        """Khởi tạo đối tượng gpiozero trên Raspberry Pi."""
        # 1. Servo (0 độ = Khóa chốt, 90 độ = Mở chốt)
        self.servo = AngularServo(
            self.servo_pin,
            min_angle=0,
            max_angle=180,
            min_pulse_width=0.0005,
            max_pulse_width=0.0025,
        )
        self.servo.angle = 0  # Mặc định hạ chốt khóa
        self.lock_state = "LOCKED"

        # 2. Cảm biến từ MC-38 kết nối chân GPIO với GND (có điện trở kéo pull_up=True)
        # Khi cửa ĐÓNG: 2 nửa nam châm chạm nhau -> công tắc đóng -> GPIO nối GND (pressed)
        # Khi cửa MỞ: nam châm tách xa -> công tắc hở -> GPIO mức cao (released)
        self.door_sensor = Button(self.door_sensor_pin, pull_up=True, bounce_time=0.1)

        def _handle_door_pressed():
            # Button pressed = mạch kín (nam châm chạm) -> Thường là CỬA ĐÓNG
            new_state = "OPEN" if self.invert_door_sensor else "CLOSED"
            self._update_door_state(new_state)

        def _handle_door_released():
            # Button released = mạch hở (nam châm tách) -> Thường là CỬA MỞ
            new_state = "CLOSED" if self.invert_door_sensor else "OPEN"
            self._update_door_state(new_state)

        self.door_sensor.when_pressed = _handle_door_pressed
        self.door_sensor.when_released = _handle_door_released

        # Đọc trạng thái ban đầu
        initial_pressed = self.door_sensor.is_pressed
        if self.invert_door_sensor:
            self.door_state = "OPEN" if initial_pressed else "CLOSED"
        else:
            self.door_state = "CLOSED" if initial_pressed else "OPEN"

        # 3. Đèn báo LED
        self.red_led = LED(self.red_led_pin)
        self.green_led = LED(self.green_led_pin)
        self.red_led.off()
        self.green_led.off()

    def _update_door_state(self, new_state: str):
        with self._lock:
            if self.door_state == new_state:
                return
            self.door_state = new_state
            print(f"🧲 [MC-38] Cảm biến từ phát hiện: CỬA {new_state}!", flush=True)

        if callable(self.on_door_state_change):
            try:
                self.on_door_state_change(new_state)
            except Exception as e:
                print(f"[Error in on_door_state_change]: {e}")

    # ── ĐIỀU KHIỂN KHÓA SERVO (Ổ KHÓA ĐIỆN TỬ) ─────────────────────────

    def unlock_door(self) -> bool:
        """
        Mở khóa: Servo quay lên 90 độ (Mở chốt).
        """
        with self._lock:
            self.lock_state = "UNLOCKED"
            print("🔓 [SERVO] Mở chốt khóa (Servo góc 90°)...", flush=True)

            if self.is_real_hardware:
                try:
                    self.servo.angle = 90
                    self.green_led.on()
                except Exception as e:
                    print(f"❌ [GPIO Error] Lỗi quay Servo mở: {e}")

        return True

    def lock_door(self, force: bool = False) -> bool:
        """
        Hạ chốt khóa: Servo quay về 0 độ.
        QUY TẮC AN TOÀN (Safety Interlock):
        Nếu cửa đang MỞ (MC-38 == OPEN) và không ép buộc (force=False),
        tuyệt đối KHÔNG ĐÓNG CHỐT để tránh làm gãy chốt khi người dùng đẩy cửa vào.
        """
        with self._lock:
            if not force and self.door_state == "OPEN":
                print("⚠️ [SERVO SAFETY] Cửa tủ đang MỞ (MC-38=OPEN). TỪ CHỐI hạ chốt để chống kẹt/gãy chốt!", flush=True)
                return False

            self.lock_state = "LOCKED"
            print("🔒 [SERVO] Hạ chốt khóa an toàn (Servo góc 0°)...", flush=True)

            if self.is_real_hardware:
                try:
                    self.servo.angle = 0
                    self.green_led.off()
                except Exception as e:
                    print(f"❌ [GPIO Error] Lỗi quay Servo đóng: {e}")

        return True

    # ── ĐÈN BÁO & CÒI CẢNH BÁO ──────────────────────────────────────────

    def flash_red(self, duration: float = 2.0):
        """Bật LED đỏ cảnh báo trong thời gian duration (giây)."""
        def _worker():
            print(f"🔴 [LED RED] Cảnh báo kích hoạt trong {duration}s...", flush=True)
            if self.is_real_hardware:
                try:
                    self.red_led.on()
                except Exception:
                    pass
            time.sleep(duration)
            if self.is_real_hardware:
                try:
                    self.red_led.off()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def flash_green(self, duration: float = 2.0):
        """Bật LED xanh báo thành công trong thời gian duration (giây)."""
        def _worker():
            if self.is_real_hardware:
                try:
                    self.green_led.on()
                except Exception:
                    pass
            time.sleep(duration)
            if self.is_real_hardware and self.lock_state == "LOCKED":
                try:
                    self.green_led.off()
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    # ── PHƯƠNG THỨC MÔ PHỎNG DÀNH CHO TEST TRÊN PC/WEB ─────────────────

    def simulate_set_door(self, state: str):
        """Mô phỏng thay đổi trạng thái cửa (OPEN hoặc CLOSED) từ Web Admin/Kiosk."""
        state = state.upper()
        if state not in ("OPEN", "CLOSED"):
            return
        self._update_door_state(state)

    def get_status(self) -> dict:
        """Lấy trạng thái tổng thể của phần cứng."""
        return {
            "lock_state": self.lock_state,    # "LOCKED" hoặc "UNLOCKED"
            "door_state": self.door_state,    # "CLOSED" hoặc "OPEN"
            "is_real_hardware": self.is_real_hardware,
            "servo_pin": self.servo_pin,
            "door_sensor_pin": self.door_sensor_pin,
        }

    def cleanup(self):
        """Giải phóng chân GPIO khi tắt hệ thống."""
        if self.is_real_hardware:
            try:
                self.servo.close()
                self.door_sensor.close()
                self.red_led.close()
                self.green_led.close()
                print("🔌 [GPIO] Đã giải phóng toàn bộ chân GPIO an toàn.")
            except Exception:
                pass

