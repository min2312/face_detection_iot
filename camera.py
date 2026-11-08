"""
camera.py - Module quản lý Camera (USB Camera, IP Camera, Laptop Webcam)
Sử dụng đa luồng (threading) để lấy frame liên tục, tránh hiện tượng trễ hình (latency) trên Raspberry Pi.
"""

import os
import threading
import time
from typing import Optional, Union
import cv2
import numpy as np


class Camera:
    def __init__(self, device: Optional[Union[str, int]] = None):
        # 1. Ưu tiên kiểm tra CAMERA_IP (Webcam phát từ Laptop qua Wi-Fi)
        cam_ip = os.environ.get("CAMERA_IP", "").strip()
        if cam_ip:
            cam_port = os.environ.get("CAMERA_PORT", "5000").strip()
            cam_ep = os.environ.get("CAMERA_ENDPOINT", "/video").strip()
            if not cam_ep.startswith("/"):
                cam_ep = "/" + cam_ep
            self.device = f"http://{cam_ip}:{cam_port}{cam_ep}"
        else:
            # 2. Nếu không có CAMERA_IP, kiểm tra CAMERA_DEVICE hoặc đối số truyền vào
            if device is None:
                device = os.environ.get("CAMERA_DEVICE", 0)

            # Nếu là số nguyên dạng chuỗi ("0", "1") -> ép về int
            if isinstance(device, str) and device.isdigit():
                self.device = int(device)
            else:
                self.device = device

        self.cap: Optional[cv2.VideoCapture] = None
        self.frame: Optional[np.ndarray] = None
        self.is_running = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Khởi động luồng đọc camera."""
        if self.is_running:
            return

        print(f"📷 Đang mở camera: {self.device} ...", flush=True)
        if isinstance(self.device, int):
            # Nếu chạy trên Linux có hỗ trợ V4L2
            self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2 if hasattr(cv2, "CAP_V4L2") else cv2.CAP_ANY)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
        else:
            self.cap = cv2.VideoCapture(self.device)

        if not self.cap.isOpened():
            print(f"⚠️ Không thể mở camera {self.device}. Sẽ thử lại trong luồng nền...")

        self.is_running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        fail_count = 0
        while self.is_running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(1.0)
                try:
                    if isinstance(self.device, int):
                        self.cap = cv2.VideoCapture(self.device)
                    else:
                        self.cap = cv2.VideoCapture(self.device)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                except Exception as e:
                    print(f"Lỗi mở camera: {e}")
                    continue

            try:
                success, frame = self.cap.read()
            except Exception:
                success = False
                frame = None

            if success and frame is not None:
                fail_count = 0
                with self._lock:
                    self.frame = frame
                time.sleep(0.01)  # Giảm tải CPU
            else:
                fail_count += 1
                # Nếu mất tín hiệu quá 15 lần (~1.5s) -> Đứt mạng hoặc camera tắt, tự kết nối lại
                if fail_count >= 15:
                    print(f"⚠️ Mất kết nối stream camera ({self.device}). Đang tự động kết nối lại...", flush=True)
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None
                    fail_count = 0
                    time.sleep(1.0)
                else:
                    time.sleep(0.05)

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Lấy bản copy frame mới nhất từ camera."""
        with self._lock:
            if self.frame is not None:
                return self.frame.copy()
        return None

    def stop(self):
        """Dừng camera và giải phóng tài nguyên."""
        self.is_running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        print("📷 Đã tắt camera.", flush=True)

