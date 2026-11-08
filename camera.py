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
    def __init__(self, device: Union[str, int] = 0):
        # Hỗ trợ truyền qua biến môi trường CAMERA_DEVICE
        env_dev = os.environ.get("CAMERA_DEVICE")
        if env_dev:
            device = env_dev

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
        else:
            self.cap = cv2.VideoCapture(self.device)

        # Cấu hình độ phân giải phù hợp cho Pi (640x480 để đạt FPS cao)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        if not self.cap.isOpened():
            print(f"⚠️ Không thể mở camera {self.device}. Sẽ thử lại trong luồng nền...")

        self.is_running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        retry_delay = 2.0
        while self.is_running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(retry_delay)
                try:
                    if isinstance(self.device, int):
                        self.cap = cv2.VideoCapture(self.device)
                    else:
                        self.cap = cv2.VideoCapture(self.device)
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                except Exception:
                    continue

            success, frame = self.cap.read()
            if success and frame is not None:
                with self._lock:
                    self.frame = frame
            else:
                # Mất tín hiệu frame, tạm nghỉ trước khi đọc lại
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

