"""
locker_manager.py - Máy trạng thái (State Machine) điều phối toàn bộ quy trình Tủ Đồ Thông Minh:
1. Luồng Cất Đồ (Deposit / Check-in)
2. Luồng Lấy Đồ (Withdraw / Check-out)
3. Khóa liên động An toàn (Safety Interlock giữa Cảm biến từ MC-38 và Khóa Servo)
"""

from datetime import datetime
from pathlib import Path
import threading
import time
from typing import Dict, Optional
import cv2
import numpy as np

from camera import Camera
from database import LockerDatabase
from gpio_controller import HardwareController
from recognition import FaceEngine


class LockerState:
    IDLE = "IDLE"                                     # Chế độ chờ (Sẵn sàng)
    DEPOSIT_SCANNING = "DEPOSIT_SCANNING"             # Đang quét mặt đăng ký cất đồ
    DEPOSIT_DOOR_WAIT_OPEN = "DEPOSIT_DOOR_WAIT_OPEN" # Đã mở servo, chờ user kéo mở cửa
    DEPOSIT_DOOR_OPEN = "DEPOSIT_DOOR_OPEN"           # Cửa đang mở (MC-38 hở) - Chờ user bỏ đồ
    DEPOSIT_SUCCESS = "DEPOSIT_SUCCESS"               # User đã đóng cửa - Đã hạ chốt servo
    
    WITHDRAW_SCANNING = "WITHDRAW_SCANNING"           # Đang quét mặt xác thực lấy đồ
    WITHDRAW_DOOR_WAIT_OPEN = "WITHDRAW_DOOR_WAIT_OPEN" # Đã mở servo, chờ user kéo mở cửa
    WITHDRAW_DOOR_OPEN = "WITHDRAW_DOOR_OPEN"         # Cửa đang mở - Chờ user lấy đồ ra
    WITHDRAW_SUCCESS = "WITHDRAW_SUCCESS"             # User đã đóng cửa - Đã hạ chốt servo
    
    ERROR = "ERROR"                                   # Lỗi (Giả mạo / Hết thời gian chờ)


class LockerManager:
    def __init__(
        self,
        camera: Camera,
        engine: FaceEngine,
        gpio: HardwareController,
        db: LockerDatabase,
        locker_id: int = 1
    ):
        self.camera = camera
        self.engine = engine
        self.gpio = gpio
        self.db = db
        self.locker_id = locker_id

        self.current_state = LockerState.IDLE
        self.state_message = "Hệ thống sẵn sàng. Vui lòng chọn Cất đồ hoặc Lấy đồ."
        self.current_user_name = ""
        self.state_start_time = time.time()

        self._lock = threading.Lock()
        self._loop_running = True
        self._action_thread: Optional[threading.Thread] = None

        # Đăng ký callback khi cảm biến từ MC-38 thay đổi trạng thái
        self.gpio.on_door_state_change = self._handle_hardware_door_event

        # Khởi động thread giám sát liên tục
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    # ── XỬ LÝ SỰ KIỆN CẢM BIẾN TỪ MC-38 ─────────────────────────────────

    def _handle_hardware_door_event(self, door_state: str):
        """Được gọi tự động mỗi khi MC-38 phát hiện cửa Mở hoặc Đóng."""
        with self._lock:
            state = self.current_state

            # TRƯỜNG HỢP 1: ĐANG TRONG TIẾN TRÌNH CẤT ĐỒ
            if state == LockerState.DEPOSIT_DOOR_WAIT_OPEN and door_state == "OPEN":
                self.current_state = LockerState.DEPOSIT_DOOR_OPEN
                self.state_message = "🚪 Cửa đang mở. Vui lòng bỏ đồ vào tủ rồi đóng cửa lại."
                print("👉 [Locker] Cửa đã mở để cất đồ.", flush=True)

            elif state == LockerState.DEPOSIT_DOOR_OPEN and door_state == "CLOSED":
                # Người dùng đã bỏ đồ xong và khép chặt cửa lại!
                print("👉 [Locker] Người dùng đã đóng cửa tủ sau khi cất đồ. Kích hoạt Servo khóa lại!", flush=True)
                self.gpio.lock_door()
                self.current_state = LockerState.DEPOSIT_SUCCESS
                self.state_message = "🔒 Tủ đã khóa an toàn. Cất đồ thành công!"
                self.gpio.flash_green(2.0)
                # Tự động quay về IDLE sau 4 giây
                threading.Timer(4.0, self.reset_to_idle).start()

            # TRƯỜNG HỢP 2: ĐANG TRONG TIẾN TRÌNH LẤY ĐỒ
            elif state == LockerState.WITHDRAW_DOOR_WAIT_OPEN and door_state == "OPEN":
                self.current_state = LockerState.WITHDRAW_DOOR_OPEN
                self.state_message = "🚪 Cửa đang mở. Vui lòng lấy đồ ra rồi đóng cửa lại."
                print("👉 [Locker] Cửa đã mở để lấy đồ.", flush=True)

            elif state == LockerState.WITHDRAW_DOOR_OPEN and door_state == "CLOSED":
                # Người dùng đã lấy đồ xong và khép cửa lại!
                print("👉 [Locker] Người dùng đã đóng cửa tủ sau khi lấy đồ. Kích hoạt Servo khóa & giải phóng tủ!", flush=True)
                self.gpio.lock_door()
                # Giải phóng tủ trong cơ sở dữ liệu
                self.db.release_locker(self.locker_id)
                self.db.log_event("WITHDRAW", self.locker_id, self.current_user_name, note="Đã hoàn tất lấy đồ")
                self.current_state = LockerState.WITHDRAW_SUCCESS
                self.state_message = "🔒 Tủ đã khóa. Cảm ơn quý khách đã sử dụng dịch vụ!"
                self.gpio.flash_green(2.0)
                # Tự động quay về IDLE sau 4 giây
                threading.Timer(4.0, self.reset_to_idle).start()

    # ── KHỞI TẠO HÀNH ĐỘNG TỪ GIAO DIỆN WEB ─────────────────────────────

    def start_deposit(self, user_name: str) -> Tuple[bool, str]:
        """Bắt đầu quy trình Cất Đồ."""
        with self._lock:
            locker = self.db.get_locker(self.locker_id)
            if locker.get("status") == "OCCUPIED":
                return False, f"Tủ đang có người sử dụng ({locker.get('occupant_name')})! Không thể cất tiếp."

            if self.current_state != LockerState.IDLE:
                return False, "Hệ thống đang bận xử lý tác vụ khác."

            self.current_user_name = user_name.strip() or f"Khách_{int(time.time())%10000}"
            self.current_state = LockerState.DEPOSIT_SCANNING
            self.state_message = f"📸 Đang quét khuôn mặt '{self.current_user_name}'. Vui lòng nhìn thẳng vào camera..."
            self.state_start_time = time.time()

            # Chạy thread quét mặt đăng ký
            threading.Thread(target=self._process_deposit_scan, daemon=True).start()
            return True, "Bắt đầu quét khuôn mặt cất đồ."

    def start_withdraw(self) -> Tuple[bool, str]:
        """Bắt đầu quy trình Lấy Đồ."""
        with self._lock:
            locker = self.db.get_locker(self.locker_id)
            if locker.get("status") != "OCCUPIED":
                return False, "Tủ hiện đang trống, không có đồ để lấy!"

            if self.current_state != LockerState.IDLE:
                return False, "Hệ thống đang bận xử lý tác vụ khác."

            self.current_user_name = locker.get("occupant_name", "Người gửi")
            self.current_state = LockerState.WITHDRAW_SCANNING
            self.state_message = "📸 Vui lòng nhìn thẳng vào camera để xác thực khuôn mặt lấy đồ..."
            self.state_start_time = time.time()

            # Chạy thread quét mặt xác thực
            threading.Thread(target=self._process_withdraw_scan, daemon=True).start()
            return True, "Bắt đầu quét khuôn mặt lấy đồ."

    def reset_to_idle(self):
        """Khôi phục hệ thống về trạng thái sẵn sàng."""
        with self._lock:
            # Nếu cửa đang đóng thì chắc chắn servo đã khóa
            if self.gpio.door_state == "CLOSED":
                self.gpio.lock_door()
            self.current_state = LockerState.IDLE
            self.current_user_name = ""
            self.state_message = "Hệ thống sẵn sàng. Vui lòng chọn Cất đồ hoặc Lấy đồ."
            print("🔄 [Locker] Hệ thống đã trở về trạng thái IDLE.", flush=True)

    # ── LUỒNG XỬ LÝ QUÉT MẶT CẤT ĐỒ ────────────────────────────────────

    def _process_deposit_scan(self):
        timeout = 15.0  # Chờ tối đa 15 giây
        t0 = time.time()
        best_face_data = None
        consecutive_real = 0

        while time.time() - t0 < timeout:
            with self._lock:
                if self.current_state != LockerState.DEPOSIT_SCANNING:
                    return

            frame = self.camera.get_latest_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            _, results = self.engine.analyze_frame(frame)
            if not results:
                time.sleep(0.05)
                continue

            face = results[0]  # Lấy khuôn mặt đầu tiên
            if not face["is_real"]:
                consecutive_real = 0
                self.state_message = f"🚨 CẢNH BÁO: Phát hiện ảnh giả mạo ({face['live_label']})! Vui lòng dùng mặt thật."
                self.gpio.flash_red(1.0)
                # Ghi log phát hiện giả mạo
                self._save_event_photo(frame, "SPOOF_DEPOSIT")
                time.sleep(0.3)
                continue

            # Mặt thật (Real Face)
            consecutive_real += 1
            if consecutive_real >= 3 and face["feature"] is not None:
                best_face_data = face
                best_frame = frame.copy()
                break

            time.sleep(0.05)

        with self._lock:
            if self.current_state != LockerState.DEPOSIT_SCANNING:
                return

            if best_face_data is not None:
                # Lưu ảnh chân dung
                photo_path = self._save_event_photo(best_frame, f"deposit_{self.current_user_name}")

                # Lưu vào database
                self.db.occupy_locker(
                    self.locker_id,
                    self.current_user_name,
                    best_face_data["feature"],
                    photo_path
                )
                self.db.log_event(
                    "DEPOSIT",
                    self.locker_id,
                    self.current_user_name,
                    liveness_score=best_face_data["live_score"],
                    photo_path=photo_path,
                    note="Đăng ký cất đồ thành công"
                )

                # MỞ KHÓA SERVO
                self.gpio.unlock_door()
                self.gpio.flash_green(1.5)

                # Chuyển trạng thái sang chờ người dùng mở cửa
                self.current_state = LockerState.DEPOSIT_DOOR_WAIT_OPEN
                self.state_message = "🔓 Đã mở khóa Servo! Vui lòng kéo mở cửa tủ để cất đồ."
                print(f"✅ [Deposit] Đã mở khóa cho '{self.current_user_name}'. Chờ mở cửa...", flush=True)

                # Khởi động bộ đếm nhắc nhở mở cửa (nếu sau 30s ko mở thì tự khóa lại)
                threading.Thread(target=self._wait_open_timeout_guard, args=(LockerState.DEPOSIT_DOOR_WAIT_OPEN,), daemon=True).start()
            else:
                self.current_state = LockerState.ERROR
                self.state_message = "❌ Không nhận diện được khuôn mặt thật hoặc hết thời gian chờ."
                self.gpio.flash_red(2.0)
                threading.Timer(4.0, self.reset_to_idle).start()

    # ── LUỒNG XỬ LÝ QUÉT MẶT LẤY ĐỒ ────────────────────────────────────

    def _process_withdraw_scan(self):
        timeout = 15.0
        t0 = time.time()
        locker = self.db.get_locker(self.locker_id)
        target_emb = locker.get("embedding")
        occupant_name = locker.get("occupant_name", "Người gửi")

        if target_emb is None:
            with self._lock:
                self.current_state = LockerState.ERROR
                self.state_message = "❌ Lỗi dữ liệu khuôn mặt ngăn tủ!"
                threading.Timer(3.0, self.reset_to_idle).start()
            return

        consecutive_match = 0
        matched_face = None
        matched_frame = None

        while time.time() - t0 < timeout:
            with self._lock:
                if self.current_state != LockerState.WITHDRAW_SCANNING:
                    return

            frame = self.camera.get_latest_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            _, results = self.engine.analyze_frame(frame, target_embedding=target_emb, target_name=occupant_name)
            if not results:
                time.sleep(0.05)
                continue

            face = results[0]
            if not face["is_real"]:
                consecutive_match = 0
                self.state_message = f"🚨 CẢNH BÁO: Phát hiện ảnh giả mạo ({face['live_label']})! Từ chối mở cửa."
                self.gpio.flash_red(1.0)
                self._save_event_photo(frame, "SPOOF_WITHDRAW")
                time.sleep(0.3)
                continue

            # Mặt thật -> Kiểm tra độ tương đồng
            if face["is_match"]:
                consecutive_match += 1
                if consecutive_match >= 2:
                    matched_face = face
                    matched_frame = frame.copy()
                    break
            else:
                consecutive_match = 0
                self.state_message = f"❌ Sai khuôn mặt (Độ khớp: {face['sim_score']:.2f}). Không đúng người gửi!"
                self.gpio.flash_red(0.5)

            time.sleep(0.05)

        with self._lock:
            if self.current_state != LockerState.WITHDRAW_SCANNING:
                return

            if matched_face is not None:
                photo_path = self._save_event_photo(matched_frame, f"withdraw_{occupant_name}")

                # MỞ KHÓA SERVO
                self.gpio.unlock_door()
                self.gpio.flash_green(1.5)

                self.current_state = LockerState.WITHDRAW_DOOR_WAIT_OPEN
                self.state_message = f"🔓 Xác thực thành công ({occupant_name})! Vui lòng kéo mở cửa tủ để lấy đồ."
                print(f"✅ [Withdraw] Khớp người gửi '{occupant_name}'. Đã mở servo, chờ mở cửa...", flush=True)

                # Khởi động bộ đếm nhắc nhở mở cửa
                threading.Thread(target=self._wait_open_timeout_guard, args=(LockerState.WITHDRAW_DOOR_WAIT_OPEN,), daemon=True).start()
            else:
                self.current_state = LockerState.ERROR
                self.state_message = "❌ Xác thực thất bại hoặc hết thời gian quét mặt."
                self.gpio.flash_red(2.0)
                self.db.log_event("UNAUTHORIZED", self.locker_id, note="Xác thực lấy đồ thất bại")
                threading.Timer(4.0, self.reset_to_idle).start()

    # ── TIMEOUT GUARD ──────────────────────────────────────────────────

    def _wait_open_timeout_guard(self, expected_state: str):
        """Nếu mở servo xong nhưng sau 20 giây người dùng không hề kéo cửa tủ ra -> Tự động khóa lại."""
        time.sleep(20.0)
        with self._lock:
            if self.current_state == expected_state:
                print("⏱️ [Timeout] Đã mở khóa nhưng người dùng không kéo cửa. Đang khóa lại...", flush=True)
                self.gpio.lock_door(force=True)
                self.current_state = LockerState.IDLE
                self.state_message = "⏱️ Hết thời gian chờ mở cửa. Hệ thống đã khóa lại."

    def _monitor_loop(self):
        """Luồng giám sát trạng thái cửa mở quá lâu (Door Open Alarm)."""
        door_open_time = None
        while self._loop_running:
            door_state = self.gpio.door_state
            if door_state == "OPEN":
                if door_open_time is None:
                    door_open_time = time.time()
                elif time.time() - door_open_time > 45.0:
                    # Cửa mở quá 45 giây chưa đóng -> Cảnh báo
                    print("⚠️ [ALARM] CỬA TỦ ĐANG BỊ MỞ QUÁ 45 GIÂY CHƯA ĐÓNG!", flush=True)
                    self.gpio.flash_red(1.0)
                    time.sleep(3.0)
            else:
                door_open_time = None
            time.sleep(0.5)

    def admin_emergency_unlock(self) -> bool:
        """Admin cưỡng chế mở khóa Servo."""
        with self._lock:
            self.gpio.unlock_door()
            self.db.log_event("ADMIN_UNLOCK", self.locker_id, note="Mở khóa khẩn cấp bởi Admin")
            self.state_message = "⚠️ Admin đã kích hoạt Mở khóa khẩn cấp!"
            return True

    def admin_force_lock(self) -> bool:
        """Admin ép đóng chốt Servo."""
        with self._lock:
            res = self.gpio.lock_door(force=True)
            self.reset_to_idle()
            return res

    def _save_event_photo(self, frame: np.ndarray, prefix: str) -> str:
        """Lưu ảnh chụp sự kiện ra đĩa để tra cứu nhật ký."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.jpg"
        filepath = self.db.faces_dir / filename
        cv2.imwrite(str(filepath), frame)
        return filename

    def get_full_status(self) -> dict:
        """Trả về trạng thái tổng thể cho Web Kiosk & Admin Dashboard."""
        locker = self.db.get_locker(self.locker_id)
        hw_status = self.gpio.get_status()

        return {
            "state": self.current_state,
            "message": self.state_message,
            "user_name": self.current_user_name,
            "door_state": hw_status["door_state"],      # "OPEN" hoặc "CLOSED"
            "lock_state": hw_status["lock_state"],      # "LOCKED" hoặc "UNLOCKED"
            "is_real_hardware": hw_status["is_real_hardware"],
            "locker": {
                "id": self.locker_id,
                "name": locker.get("name", "Tủ số 1"),
                "status": locker.get("status", "AVAILABLE"),
                "occupant_name": locker.get("occupant_name"),
                "deposit_time": locker.get("deposit_time"),
                "photo_path": locker.get("photo_path"),
            }
        }

