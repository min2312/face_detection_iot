"""
anti_spoof.py - Module Chống Giả Mạo Khuôn Mặt (Face Anti-Spoofing / Liveness Detection)
Sử dụng model MiniFASNetV2 ONNX chạy trực tiếp trên OpenCV DNN.
Phát hiện:
- Ảnh in giấy (Print Attack)
- Màn hình điện thoại / máy tính bảng (Replay Attack)
- Người thật (Live / Real Face)
"""

from pathlib import Path
from typing import Tuple
import cv2
import numpy as np


class AntiSpoofDetector:
    def __init__(self, model_path: str = None, threshold: float = 0.70):
        """
        Khởi tạo detector chống giả mạo.
        :param model_path: Đường dẫn tới file MiniFASNetV2.onnx
        :param threshold: Ngưỡng xác suất người thật (mặc định 0.70)
        """
        if model_path is None:
            base_dir = Path(__file__).resolve().parent
            model_path = str(base_dir / "models" / "MiniFASNetV2.onnx")

        self.model_path = model_path
        self.threshold = threshold

        if not Path(model_path).exists():
            raise FileNotFoundError(f"Không tìm thấy model Anti-Spoof: {model_path}")

        # Nạp model qua OpenCV DNN (chạy native C++, tối ưu CPU ARM / x86)
        self.net = cv2.dnn.readNetFromONNX(self.model_path)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

        # Scale factor mở rộng bounding box để lấy thêm texture viền/nền
        self.scale_factor = 2.7
        self.input_size = (80, 80)

    def _crop_face_with_margin(
        self, img: np.ndarray, bbox: list
    ) -> Tuple[np.ndarray, bool]:
        """
        Cắt vùng mặt với tỉ lệ mở rộng 2.7x xung quanh tâm khuôn mặt.
        bbox: [x, y, w, h]
        """
        h_img, w_img = img.shape[:2]
        x, y, w, h = bbox

        # Tọa độ tâm
        cx = x + w / 2.0
        cy = y + h / 2.0

        # Kích thước mở rộng
        size = int(max(w, h) * self.scale_factor)

        x1 = int(cx - size / 2.0)
        y1 = int(cy - size / 2.0)
        x2 = x1 + size
        y2 = y1 + size

        # Padding nếu bbox mở rộng ra ngoài frame
        pad_x1 = max(0, -x1)
        pad_y1 = max(0, -y1)
        pad_x2 = max(0, x2 - w_img)
        pad_y2 = max(0, y2 - h_img)

        # Cắt trong phạm vi ảnh
        crop_x1 = max(0, x1)
        crop_y1 = max(0, y1)
        crop_x2 = min(w_img, x2)
        crop_y2 = min(h_img, y2)

        cropped = img[crop_y1:crop_y2, crop_x1:crop_x2]
        if cropped.size == 0:
            return np.zeros((self.input_size[1], self.input_size[0], 3), dtype=np.uint8), False

        # Thêm viền đen (padding) nếu chạm mép ngoài
        if pad_x1 > 0 or pad_y1 > 0 or pad_x2 > 0 or pad_y2 > 0:
            cropped = cv2.copyMakeBorder(
                cropped, pad_y1, pad_y2, pad_x1, pad_x2,
                cv2.BORDER_CONSTANT, value=[0, 0, 0]
            )

        resized = cv2.resize(cropped, self.input_size)
        return resized, True

    def check_liveness(
        self, img: np.ndarray, bbox: list
    ) -> Tuple[bool, float, str]:
        """
        Kiểm tra độ sống (Liveness) của khuôn mặt.
        :param img: Frame ảnh BGR
        :param bbox: [x, y, w, h] của khuôn mặt
        :return: (is_real: bool, confidence: float, label: str)
        """
        cropped, ok = self._crop_face_with_margin(img, bbox)
        if not ok:
            return False, 0.0, "INVALID_CROP"

        # Tiền xử lý: BGR, tỉ lệ [0, 1], shape [1, 3, 80, 80]
        blob = cv2.dnn.blobFromImage(
            cropped,
            scalefactor=1.0 / 255.0,
            size=self.input_size,
            mean=(0, 0, 0),
            swapRB=False,
            crop=False
        )

        self.net.setInput(blob)
        preds = self.net.forward()  # shape (1, 3)

        # Tính Softmax
        exp_preds = np.exp(preds[0] - np.max(preds[0]))
        probs = exp_preds / np.sum(exp_preds)

        # Class 0: Print Attack (Ảnh in)
        # Class 1: Real Face (Người thật)
        # Class 2: Replay Attack (Màn hình điện thoại/máy tính)
        p_print = float(probs[0])
        p_real = float(probs[1])
        p_replay = float(probs[2])

        is_real = (p_real >= self.threshold) and (np.argmax(probs) == 1)

        if is_real:
            label = "REAL"
            conf = p_real
        else:
            if p_replay > p_print:
                label = "SPOOF_SCREEN"  # Màn hình điện thoại
                conf = p_replay
            else:
                label = "SPOOF_PRINT"   # Ảnh in giấy
                conf = p_print

        return is_real, conf, label

