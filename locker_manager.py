"""
locker_manager.py - Máy trạng thái (State Machine) điều phối 4 Ngăn Tủ Thông Minh:
1. Mở Servo tức thì (0 delay) ngay khi nhận diện đúng.
2. Giữ nguyên chốt khi cửa tủ đang mở.
3. Chờ đúng 1.0 giây sau khi đóng cửa tủ rồi mới hạ chốt Servo khóa lại.
4. Tự động tìm ngăn tủ trống khi Cất đồ, và tự động tìm đúng số tủ khi Lấy đồ.
"""

from datetime import datetime
from pathlib import Path
import threading
import time
from typing import Dict, Optional, Tuple
import cv2
import numpy as np

from database import LockerDatabase
from gpio_controller import HardwareController
from recognition import FaceEngine


class LockerState:
    IDLE = "IDLE"
    DEPOSIT_SCANNING = "DEPOSIT_SCANNING"
    DEPOSIT_DOOR_WAIT_OPEN = "DEPOSIT_DOOR_WAIT_OPEN"
    DEPOSIT_DOOR_OPEN = "DEPOSIT_DOOR_OPEN"
    DEPOSIT_SUCCESS = "DEPOSIT_SUCCESS"

    WITHDRAW_SCANNING = "WITHDRAW_SCANNING"
    WITHDRAW_DOOR_WAIT_OPEN = "WITHDRAW_DOOR_WAIT_OPEN"
    WITHDRAW_DOOR_OPEN = "WITHDRAW_DOOR_OPEN"
    WITHDRAW_SUCCESS = "WITHDRAW_SUCCESS"

    ERROR = "ERROR"


class LockerManager:
    def __init__(
        self,
        engine: FaceEngine,
        gpio: HardwareController,
        db: LockerDatabase,
    ):
        self.engine = engine
        self.gpio = gpio
        self.db = db

        self.current_state = LockerState.IDLE
        self.state_message = "Hệ thống sẵn sàng. Vui lòng bấm Cất đồ hoặc Lấy đồ."
        self.active_locker_id: Optional[int] = None
        self.current_user_name: str = ""
        self.state_start_time = time.time()

        self._lock = threading.Lock()
        self._action_thread: Optional[threading.Thread] = None

        # Đăng ký callback khi 1 trong 4 cảm biến từ MC-38 đổi trạng thái
        self.gpio.on_door_state_change = self._handle_door_change

    # ── XỬ LÝ SỰ KIỆN CẢM BIẾN TỪ MC-38 CỦA 4 TỦ ──────────────────────

    def _handle_door_change(self, locker_id: int, door_state: str):
        """Được gọi khi cảm biến từ của Tủ `locker_id` chuyển trạng thái."""
        with self._lock:
            # Chỉ xử lý sự kiện của đúng ngăn tủ đang trong phiên giao dịch
            if self.active_locker_id != locker_id:
                return

            state = self.current_state

            # ── 1. TIẾN TRÌNH CẤT ĐỒ ────────────────────────────────────
            if state == LockerState.DEPOSIT_DOOR_WAIT_OPEN and door_state == "OPEN":
                self.current_state = LockerState.DEPOSIT_DOOR_OPEN
                self.state_message = f"🚪 Cửa Tủ số {locker_id} đang mở. Vui lòng bỏ đồ vào rồi đóng cửa lại."
                print(f"👉 [Locker {locker_id}] Cửa đã mở để cất đồ.", flush=True)

            elif state == LockerState.DEPOSIT_DOOR_OPEN and door_state == "CLOSED":
                # Người dùng đã khép cửa! Chờ đúng 1.0 giây mới hạ chốt khóa lại (Đúng yêu cầu)
                print(f"👉 [Locker {locker_id}] Người dùng đã khép cửa cất đồ. Bắt đầu đếm 1s trước khi khóa chốt...", flush=True)
                self.state_message = f"⏳ Đã khép cửa Tủ số {locker_id}. Chờ 1 giây để hạ chốt khóa..."

                def _on_deposit_locked(lid):
                    with self._lock:
                        if self.active_locker_id == lid and self.current_state == LockerState.DEPOSIT_DOOR_OPEN:
                            self.current_state = LockerState.DEPOSIT_SUCCESS
                            self.state_message = f"🔒 Tủ số {lid} đã khóa an toàn! Cất đồ thành công."
                            self.gpio.flash_green(1.5)
                            threading.Timer(3.5, self.reset_to_idle).start()

                self.gpio.schedule_lock_after_delay(locker_id, delay_seconds=1.0, callback=_on_deposit_locked)

            # ── 2. TIẾN TRÌNH LẤY ĐỒ ────────────────────────────────────
            elif state == LockerState.WITHDRAW_DOOR_WAIT_OPEN and door_state == "OPEN":
                self.current_state = LockerState.WITHDRAW_DOOR_OPEN
                self.state_message = f"🚪 Cửa Tủ số {locker_id} đang mở. Vui lòng lấy đồ ra rồi đóng cửa lại."
                print(f"👉 [Locker {locker_id}] Cửa đã mở để lấy đồ.", flush=True)

            elif state == LockerState.WITHDRAW_DOOR_OPEN and door_state == "CLOSED":
                # Người dùng đã khép cửa sau khi lấy đồ! Chờ đúng 1.0 giây mới hạ chốt khóa
                print(f"👉 [Locker {locker_id}] Người dùng đã khép cửa lấy đồ. Bắt đầu đếm 1s trước khi khóa chốt & giải phóng...", flush=True)
                self.state_message = f"⏳ Đã khép cửa Tủ số {locker_id}. Chờ 1 giây để hạ chốt khóa..."

                def _on_withdraw_locked(lid):
                    with self._lock:
                        if self.active_locker_id == lid and self.current_state == LockerState.WITHDRAW_DOOR_OPEN:
                            self.db.release_locker(lid)
                            self.db.log_event("WITHDRAW", lid, self.current_user_name, note="Đã hoàn tất lấy đồ")
                            self.current_state = LockerState.WITHDRAW_SUCCESS
                            self.state_message = f"🔒 Tủ số {lid} đã khóa. Cảm ơn quý khách đã sử dụng dịch vụ!"
                            self.gpio.flash_green(1.5)
                            threading.Timer(3.5, self.reset_to_idle).start()

                self.gpio.schedule_lock_after_delay(locker_id, delay_seconds=1.0, callback=_on_withdraw_locked)

    # ── KHỞI TẠO CẤT ĐỒ (TỰ ĐỘNG CHỌN NGĂN TRỐNG) ──────────────────────

    def start_deposit(self, user_name: str, target_locker_id: int = None) -> Tuple[bool, str]:
        with self._lock:
            if self.current_state != LockerState.IDLE:
                return False, "Hệ thống đang bận xử lý giao dịch khác!"

            # Nếu không chỉ định số tủ, tự động tìm ngăn tủ trống đầu tiên
            if target_locker_id is None or target_locker_id <= 0:
                avail = self.db.get_first_available_locker()
                if not avail:
                    return False, "❌ Tất cả 4 ngăn tủ đều đã có người gửi! Vui lòng quay lại sau."
                target_locker_id = avail["id"]
            else:
                l = self.db.get_locker(target_locker_id)
                if l.get("status") == "OCCUPIED":
                    return False, f"❌ Tủ số {target_locker_id} đang có người dùng!"

            self.active_locker_id = target_locker_id
            self.current_user_name = user_name.strip() or f"Khách_{int(time.time())%10000}"
            self.current_state = LockerState.DEPOSIT_SCANNING
            self.state_message = f"📸 Đang quét khuôn mặt cho '{self.current_user_name}' (Phân bổ vào Tủ số {target_locker_id})..."
            self.state_start_time = time.time()

            threading.Thread(target=self._process_deposit_scan, daemon=True).start()
            return True, f"Bắt đầu quét khuôn mặt để cất đồ vào Tủ số {target_locker_id}."

    # ── KHỞI TẠO LẤY ĐỒ (TỰ ĐỘNG NHẬN DIỆN SỐ TỦ) ───────────────────────

    def start_withdraw(self) -> Tuple[bool, str]:
        with self._lock:
            if self.current_state != LockerState.IDLE:
                return False, "Hệ thống đang bận xử lý giao dịch khác!"

            # Kiểm tra xem có tủ nào đang có người gửi không
            all_lockers = self.db.get_all_lockers()
            occupied = [l for l in all_lockers if l.get("status") == "OCCUPIED"]
            if not occupied:
                return False, "❌ Hiện tại cả 4 ngăn tủ đều đang trống, không có đồ để lấy!"

            self.current_state = LockerState.WITHDRAW_SCANNING
            self.state_message = "📸 Vui lòng nhìn thẳng vào camera để nhận diện lấy đồ..."
            self.state_start_time = time.time()
            self.active_locker_id = None
            self.current_user_name = ""

            threading.Thread(target=self._process_withdraw_scan, daemon=True).start()
            return True, "Bắt đầu quét khuôn mặt để lấy đồ."

    def reset_to_idle(self):
        with self._lock:
            # Khóa chốt an toàn các tủ nếu cửa đang đóng
            for i in range(1, 5):
                if self.gpio.door_states.get(i) == "CLOSED":
                    self.gpio.lock_locker(i)
            self.current_state = LockerState.IDLE
            self.active_locker_id = None
            self.current_user_name = ""
            self.state_message = "Hệ thống sẵn sàng. Vui lòng bấm Cất đồ hoặc Lấy đồ."
            print("🔄 [Locker] Đã trở về trạng thái IDLE sẵn sàng.", flush=True)

    # ── LUỒNG XỬ LÝ QUÉT MẶT CẤT ĐỒ ────────────────────────────────────

    def _process_deposit_scan(self):
        timeout = 15.0
        t0 = time.time()
        best_face_data = None
        consecutive_real = 0
        lid = self.active_locker_id

        while time.time() - t0 < timeout:
            with self._lock:
                if self.current_state != LockerState.DEPOSIT_SCANNING:
                    return

            analysis = self.engine.get_latest_analysis()
            if not analysis or not analysis.get("has_face"):
                time.sleep(0.08)
                continue

            if not analysis["is_real"]:
                consecutive_real = 0
                self.state_message = f"🚨 CẢNH BÁO: Phát hiện ảnh giả mạo ({analysis['live_label']})! Vui lòng dùng mặt thật."
                self.gpio.flash_red(1.0)
                if analysis.get("raw_frame") is not None:
                    self._save_event_photo(analysis["raw_frame"], f"SPOOF_DEP_T{lid}")
                time.sleep(0.4)
                continue

            # Người thật (Real Face)
            consecutive_real += 1
            if consecutive_real >= 2 and analysis["feature"] is not None:
                best_face_data = analysis
                best_frame = analysis["raw_frame"]
                break

            time.sleep(0.08)

        with self._lock:
            if self.current_state != LockerState.DEPOSIT_SCANNING:
                return

            if best_face_data is not None:
                photo_path = self._save_event_photo(best_frame, f"deposit_T{lid}_{self.current_user_name}")

                # Lưu vào database
                self.db.occupy_locker(
                    lid,
                    self.current_user_name,
                    best_face_data["feature"],
                    photo_path
                )
                self.db.log_event(
                    "DEPOSIT",
                    lid,
                    self.current_user_name,
                    liveness_score=best_face_data["live_score"],
                    photo_path=photo_path,
                    note=f"Đăng ký cất đồ Tủ số {lid} thành công"
                )

                # MỞ KHÓA SERVO TỨC THÌ (0 DELAY)
                self.gpio.unlock_locker(lid)
                self.gpio.flash_green(1.5)

                self.current_state = LockerState.DEPOSIT_DOOR_WAIT_OPEN
                self.state_message = f"🔓 Đã mở khóa Tủ số {lid}! Vui lòng kéo mở cửa tủ để cất đồ."
                print(f"✅ [Deposit] Đã mở khóa Tủ {lid} cho '{self.current_user_name}'. Chờ mở cửa...", flush=True)

                # Guard timeout 25s nếu người dùng không mở cửa thì tự khóa lại
                threading.Thread(target=self._wait_open_timeout_guard, args=(lid, LockerState.DEPOSIT_DOOR_WAIT_OPEN), daemon=True).start()
            else:
                self.current_state = LockerState.ERROR
                self.state_message = "❌ Không nhận diện được khuôn mặt thật hoặc hết thời gian quét."
                self.gpio.flash_red(2.0)
                threading.Timer(4.0, self.reset_to_idle).start()

    # ── LUỒNG XỬ LÝ QUÉT MẶT LẤY ĐỒ ────────────────────────────────────

    def _process_withdraw_scan(self):
        timeout = 15.0
        t0 = time.time()
        consecutive_match = 0
        matched_face = None
        matched_locker = None
        matched_frame = None

        while time.time() - t0 < timeout:
            with self._lock:
                if self.current_state != LockerState.WITHDRAW_SCANNING:
                    return

            analysis = self.engine.get_latest_analysis()
            if not analysis or not analysis.get("has_face"):
                time.sleep(0.08)
                continue

            if not analysis["is_real"]:
                consecutive_match = 0
                self.state_message = f"🚨 CẢNH BÁO: Phát hiện ảnh giả mạo ({analysis['live_label']})! Từ chối mở cửa."
                self.gpio.flash_red(1.0)
                if analysis.get("raw_frame") is not None:
                    self._save_event_photo(analysis["raw_frame"], "SPOOF_WITHDRAW")
                time.sleep(0.4)
                continue

            # Mặt thật -> Tự động so khớp với tất cả các tủ đang có người gửi
            feature = analysis.get("feature")
            if feature is not None:
                l, score = self.db.find_occupied_locker_by_face(self.engine, feature, threshold=0.363)
                if l is not None:
                    consecutive_match += 1
                    matched_locker = l
                    if consecutive_match >= 2:
                        matched_face = analysis
                        matched_frame = analysis["raw_frame"]
                        break
                else:
                    consecutive_match = 0
                    self.state_message = f"❌ Không tìm thấy đồ của bạn trong các ngăn tủ (Độ khớp tối đa: {score:.2f})!"
                    self.gpio.flash_red(0.5)

            time.sleep(0.08)

        with self._lock:
            if self.current_state != LockerState.WITHDRAW_SCANNING:
                return

            if matched_face is not None and matched_locker is not None:
                lid = matched_locker["id"]
                occupant_name = matched_locker.get("occupant_name", "Khách")
                self.active_locker_id = lid
                self.current_user_name = occupant_name

                photo_path = self._save_event_photo(matched_frame, f"withdraw_T{lid}_{occupant_name}")

                # MỞ KHÓA SERVO TỨC THÌ (0 DELAY)
                self.gpio.unlock_locker(lid)
                self.gpio.flash_green(1.5)

                self.current_state = LockerState.WITHDRAW_DOOR_WAIT_OPEN
                self.state_message = f"🔓 Xác thực thành công: '{occupant_name}'! Đã mở khóa Tủ số {lid}. Mời kéo cửa lấy đồ."
                print(f"✅ [Withdraw] Khớp '{occupant_name}' tại Tủ số {lid}. Mở khóa tức thì!", flush=True)

                threading.Thread(target=self._wait_open_timeout_guard, args=(lid, LockerState.WITHDRAW_DOOR_WAIT_OPEN), daemon=True).start()
            else:
                self.current_state = LockerState.ERROR
                self.state_message = "❌ Không tìm thấy khuôn mặt khớp với bất kỳ ngăn tủ nào đang gửi."
                self.gpio.flash_red(2.0)
                self.db.log_event("UNAUTHORIZED", 0, note="Xác thực lấy đồ thất bại")
                threading.Timer(4.0, self.reset_to_idle).start()

    def _wait_open_timeout_guard(self, locker_id: int, expected_state: str):
        """Nếu sau 20s người dùng không hề kéo cửa ra -> Tự động khóa lại."""
        time.sleep(20.0)
        with self._lock:
            if self.active_locker_id == locker_id and self.current_state == expected_state:
                print(f"⏱️ [Timeout Tủ {locker_id}] Quá thời gian chờ mở cửa. Tự động hạ chốt khóa...", flush=True)
                self.gpio.lock_locker(locker_id, force=True)
                self.current_state = LockerState.IDLE
                self.state_message = f"⏱️ Hết thời gian chờ mở cửa Tủ số {locker_id}. Hệ thống đã khóa lại."

    def admin_emergency_unlock(self, locker_id: int) -> bool:
        """Admin mở khóa Servo ngăn tủ chỉ định (hoặc tất cả nếu locker_id = 0)."""
        if locker_id == 0:
            for i in range(1, 5):
                self.gpio.unlock_locker(i)
                self.db.log_event("ADMIN_UNLOCK", i, note="Mở khóa khẩn cấp tất cả tủ")
            self.state_message = "⚠️ Admin đã mở khóa khẩn cấp TẤT CẢ các ngăn tủ!"
        else:
            self.gpio.unlock_locker(locker_id)
            self.db.log_event("ADMIN_UNLOCK", locker_id, note=f"Mở khóa khẩn cấp Tủ {locker_id}")
            self.state_message = f"⚠️ Admin đã mở khóa khẩn cấp Tủ số {locker_id}!"
        return True

    def admin_force_lock(self, locker_id: int) -> bool:
        """Admin ép hạ chốt khóa."""
        if locker_id == 0:
            for i in range(1, 5):
                self.gpio.lock_locker(i, force=True)
        else:
            self.gpio.lock_locker(locker_id, force=True)
        self.reset_to_idle()
        return True

    def _save_event_photo(self, frame: np.ndarray, prefix: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}.jpg"
        filepath = self.db.faces_dir / filename
        cv2.imwrite(str(filepath), frame)
        return filename

    def get_full_status(self) -> dict:
        lockers = self.db.get_all_lockers()
        hw_status = self.gpio.get_status()

        return {
            "state": self.current_state,
            "message": self.state_message,
            "active_locker_id": self.active_locker_id,
            "current_user_name": self.current_user_name,
            "lock_states": hw_status["lock_states"],
            "door_states": hw_status["door_states"],
            "is_real_hardware": hw_status["is_real_hardware"],
            "lockers": [
                {
                    "id": l["id"],
                    "name": l["name"],
                    "status": l["status"],
                    "occupant_name": l.get("occupant_name"),
                    "deposit_time": l.get("deposit_time"),
                    "photo_path": l.get("photo_path"),
                    "door_state": hw_status["door_states"].get(l["id"], "CLOSED"),
                    "lock_state": hw_status["lock_states"].get(l["id"], "LOCKED"),
                }
                for l in lockers
            ]
        }
