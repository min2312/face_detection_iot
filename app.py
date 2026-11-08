"""
app.py - Web Server Flask cho Hệ thống Smart Locker
Cung cấp:
- Giao diện Kiosk Người dùng (Cất đồ / Lấy đồ)
- Giao diện Quản trị Admin (Giám sát ngăn tủ, Mở khóa khẩn cấp, Xem ảnh & Nhật ký)
- Luồng Video MJPEG thời gian thực có nhãn Anti-Spoofing & Nhận diện
- API điều khiển và SSE (Server-Sent Events) đồng bộ thời gian thực
"""

import io
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
    session,
)

from camera import Camera
from database import LockerDatabase
from gpio_controller import HardwareController
from locker_manager import LockerManager, LockerState
from recognition import FaceEngine

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.secret_key = os.environ.get("SECRET_KEY", "smart-locker-secret-2026")

# Khởi tạo các thành phần cốt lõi
print("=" * 60)
print("🚀 ĐANG KHỞI TẠO CÁC DỊCH VỤ HỆ THỐNG SMART LOCKER...")
print("=" * 60)

db = LockerDatabase(str(BASE_DIR / "data"))

servo_pin = int(os.environ.get("SERVO_PIN", "18"))
door_sensor_pin = int(os.environ.get("DOOR_SENSOR_PIN", "23"))
red_led_pin = int(os.environ.get("RED_LED_PIN", "17"))
green_led_pin = int(os.environ.get("GREEN_LED_PIN", "27"))

gpio = HardwareController(
    servo_pin=servo_pin,
    door_sensor_pin=door_sensor_pin,
    red_led_pin=red_led_pin,
    green_led_pin=green_led_pin,
)

camera = Camera(os.environ.get("CAMERA_DEVICE", "0"))
engine = FaceEngine(models_dir=str(BASE_DIR / "models"))
manager = LockerManager(camera=camera, engine=engine, gpio=gpio, db=db, locker_id=1)

# Khởi động luồng đọc camera
camera.start()

# ── LUỒNG XỬ LÝ VIDEO & AI DUY NHẤT (SINGLE PIPELINE) ─────────────────
def _video_processing_worker():
    """Luồng nền duy nhất: Đọc camera -> Xử lý AI -> Nén JPEG lưu cache (Chống nghẽn & chống đen màn hình)."""
    while True:
        try:
            frame = camera.get_latest_frame()
            if frame is None:
                # Nếu mất kết nối, tạo frame đệm thông báo
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(
                    placeholder, "Dang ket noi camera...", (150, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2
                )
                ret, jpeg = cv2.imencode(".jpg", placeholder, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                if ret:
                    with engine._cache_lock:
                        engine.latest_jpeg = jpeg.tobytes()
                time.sleep(0.5)
                continue

            is_active = (manager.current_state in (LockerState.DEPOSIT_SCANNING, LockerState.WITHDRAW_SCANNING))
            target_emb = None
            target_name = ""
            if manager.current_state == LockerState.WITHDRAW_SCANNING:
                locker = db.get_locker(manager.locker_id)
                target_emb = locker.get("embedding")
                target_name = locker.get("occupant_name", "")

            engine.process_and_cache_frame(
                frame,
                is_active_scanning=is_active,
                target_embedding=target_emb,
                target_name=target_name,
                system_status_text=manager.current_state
            )
            time.sleep(0.03)  # Giới hạn ~30 FPS
        except Exception as e:
            print(f"Lỗi worker camera: {e}")
            time.sleep(0.1)

threading.Thread(target=_video_processing_worker, daemon=True).start()

print("✅ Toàn bộ dịch vụ đã khởi động thành công!")
print("=" * 60)


# ── VIDEO STREAMING (MJPEG) ──────────────────────────────────────────

def generate_video_stream():
    """Tạo luồng MJPEG hiển thị trực tiếp camera (Chỉ truyền JPEG đã cache, cực nhẹ và không bao giờ bị đơ)."""
    while True:
        try:
            jpeg = engine.get_latest_jpeg()
            if jpeg is None:
                time.sleep(0.04)
                continue

            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
            time.sleep(0.033)
        except (GeneratorExit, StopIteration):
            break
        except Exception:
            time.sleep(0.05)


@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ── GIAO DIỆN NGƯỜI DÙNG (USER KIOSK) & ADMIN ────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/faces/<filename>")
def get_face_photo(filename):
    """Phục vụ ảnh chụp khuôn mặt từ thư mục data/faces."""
    return send_from_directory(str(db.faces_dir), filename)


# ── REST API ĐIỀU KHIỂN & TRẠNG THÁI ─────────────────────────────────

@app.route("/api/status")
def api_status():
    """Lấy trạng thái chi tiết thời gian thực."""
    return jsonify(manager.get_full_status())


@app.route("/api/action/deposit", methods=["POST"])
def action_deposit():
    """Yêu cầu bắt đầu Cất Đồ."""
    data = request.get_json(silent=True) or request.form
    name = data.get("name", "").strip() if data else ""
    ok, msg = manager.start_deposit(name)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/action/withdraw", methods=["POST"])
def action_withdraw():
    """Yêu cầu bắt đầu Lấy Đồ."""
    ok, msg = manager.start_withdraw()
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/action/cancel", methods=["POST"])
def action_cancel():
    """Hủy thao tác hiện tại và đưa hệ thống về IDLE."""
    manager.reset_to_idle()
    return jsonify({"ok": True, "message": "Đã hủy thao tác."})


# ── API ADMIN ────────────────────────────────────────────────────────

@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or request.form
    username = data.get("username", "")
    password = data.get("password", "")
    if db.verify_admin(username, password):
        session["admin_logged_in"] = True
        return jsonify({"ok": True, "message": "Đăng nhập thành công."})
    return jsonify({"ok": False, "message": "Sai tên đăng nhập hoặc mật khẩu!"}), 401


@app.route("/api/admin/unlock", methods=["POST"])
def admin_unlock():
    manager.admin_emergency_unlock()
    return jsonify({"ok": True, "message": "Đã mở khóa khẩn cấp thành công."})


@app.route("/api/admin/lock", methods=["POST"])
def admin_lock():
    res = manager.admin_force_lock()
    return jsonify({"ok": res, "message": "Đã ép đóng chốt khóa." if res else "Không thể khóa do cửa đang mở!"})


@app.route("/api/admin/release", methods=["POST"])
def admin_release():
    """Admin cưỡng chế giải phóng tủ."""
    db.release_locker(manager.locker_id)
    manager.reset_to_idle()
    db.log_event("ADMIN_UNLOCK", manager.locker_id, note="Admin giải phóng tủ cưỡng chế")
    return jsonify({"ok": True, "message": "Đã giải phóng ngăn tủ."})


@app.route("/api/admin/logs")
def get_logs():
    limit = request.args.get("limit", 50, type=int)
    return jsonify(db.get_recent_logs(limit))


@app.route("/api/admin/logs", methods=["DELETE"])
def clear_logs():
    db.clear_logs()
    return jsonify({"ok": True, "message": "Đã xóa toàn bộ nhật ký."})


# ── API GIẢ LẬP PHẦN CỨNG (CHO TEST TRÊN PC) ──────────────────────────

@app.route("/api/simulate/door", methods=["POST"])
def simulate_door():
    """Cho phép nhấn nút trên Web để mô phỏng mở hoặc đóng cửa tủ."""
    data = request.get_json(silent=True) or request.form
    state = data.get("state", "CLOSED").upper()
    gpio.simulate_set_door(state)
    return jsonify({"ok": True, "door_state": gpio.door_state})


# ── DỌN DẸP KHI THOÁT ────────────────────────────────────────────────

def cleanup_all():
    print("\n🛑 Đang tắt hệ thống Smart Locker...")
    camera.stop()
    gpio.cleanup()
    print("✅ Đã giải phóng toàn bộ tài nguyên.")


signal.signal(signal.SIGINT, lambda s, f: (cleanup_all(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda s, f: (cleanup_all(), sys.exit(0)))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"🌐 Server Smart Locker đang chạy tại http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)

