"""
recognition.py - Module phối hợp: YuNet (Detection) + AntiSpoof (Liveness) + SFace (Recognition)
Được tối ưu chạy mượt mà trên Raspberry Pi và PC.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

from anti_spoof import AntiSpoofDetector


class FaceEngine:
    def __init__(
        self,
        sim_threshold: float = 0.363,
        liveness_threshold: float = 0.70,
        models_dir: str = None
    ):
        if models_dir is None:
            base_dir = Path(__file__).resolve().parent
            models_dir = str(base_dir / "models")

        models_path = Path(models_dir)
        det_path = models_path / "face_detection_yunet_2023mar.onnx"
        rec_path = models_path / "face_recognition_sface_2021dec.onnx"
        anti_path = models_path / "MiniFASNetV2.onnx"

        if not det_path.exists() or not rec_path.exists() or not anti_path.exists():
            raise FileNotFoundError(
                f"Thiếu file model ONNX trong thư mục '{models_dir}'. Vui lòng chạy download_models.py hoặc download_models.sh."
            )

        # 1. Khởi tạo YuNet Detector (OpenCV Zoo)
        # Giới hạn số thread để không chiếm hết CPU của Pi
        cv2.setNumThreads(2)
        self.detector = cv2.FaceDetectorYN.create(
            str(det_path), "", (320, 240), 0.75, 0.3, 5000
        )

        # 2. Khởi tạo SFace Recognizer (OpenCV Zoo)
        self.recognizer = cv2.FaceRecognizerSF.create(str(rec_path), "")

        # 3. Khởi tạo Anti-Spoofing Detector (MiniFASNetV2)
        self.anti_spoof = AntiSpoofDetector(str(anti_path), threshold=liveness_threshold)

        self.sim_threshold = sim_threshold
        self.liveness_threshold = liveness_threshold

    def detect_faces(self, frame: np.ndarray) -> np.ndarray:
        """Phát hiện khuôn mặt trên frame bằng YuNet."""
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        return np.empty((0, 15), dtype=np.float32) if faces is None else faces

    def extract_feature(self, frame: np.ndarray, face: np.ndarray) -> np.ndarray:
        """Cắt chuẩn hóa và trích xuất vector đặc trưng 128 chiều bằng SFace."""
        aligned = self.recognizer.alignCrop(frame, face)
        feature = self.recognizer.feature(aligned)
        return feature

    def compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """Tính độ tương đồng Cosine giữa 2 vector khuôn mặt (0.0 đến 1.0)."""
        score = self.recognizer.match(
            feat1.reshape(1, -1),
            feat2.reshape(1, -1),
            cv2.FaceRecognizerSF_FR_COSINE
        )
        return float(score)

    def analyze_frame(
        self,
        frame: np.ndarray,
        target_embedding: Optional[np.ndarray] = None,
        target_name: str = ""
    ) -> Tuple[np.ndarray, List[Dict]]:
        """
        Phân tích toàn diện 1 frame:
        1. Tìm khuôn mặt
        2. Kiểm tra Liveness (Người thật vs Ảnh chụp điện thoại/giấy)
        3. So khớp khuôn mặt với người đăng ký (nếu có target_embedding)
        4. Vẽ kết quả trực quan lên ảnh.
        """
        annotated = frame.copy()
        faces = self.detect_faces(frame)
        results = []

        for face in faces:
            bbox = [int(v) for v in face[:4]]
            x, y, w, h = bbox

            # 1. Kiểm tra Liveness (Anti-Spoofing)
            is_real, live_score, live_label = self.anti_spoof.check_liveness(frame, bbox)

            # 2. Xử lý nhận diện khuôn mặt
            feature = None
            sim_score = 0.0
            is_match = False

            if is_real:
                feature = self.extract_feature(frame, face)
                if target_embedding is not None:
                    sim_score = self.compute_similarity(feature, target_embedding)
                    is_match = (sim_score >= self.sim_threshold)

            # Phân loại trạng thái & màu sắc hiển thị
            if not is_real:
                # Phát hiện giả mạo (Ảnh điện thoại / Giấy in)
                color = (0, 0, 255)  # Đỏ
                label_text = f"🚨 SPOOF ({live_label} {live_score*100:.0f}%)"
            elif target_embedding is not None:
                if is_match:
                    color = (0, 255, 0)  # Xanh lá
                    label_text = f"✅ {target_name} ({sim_score:.2f}) [REAL]"
                else:
                    color = (0, 165, 255)  # Cam
                    label_text = f"❌ Sai người ({sim_score:.2f}) [REAL]"
            else:
                # Người thật nhưng chưa gán mục tiêu so khớp cụ thể
                color = (0, 255, 0)  # Xanh lá
                label_text = f"👤 Người thật ({live_score*100:.0f}%)"

            # Vẽ khung chữ nhật và nhãn thông tin
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
            cv2.putText(
                annotated,
                label_text,
                (x, max(25, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                2
            )

            results.append({
                "bbox": bbox,
                "is_real": is_real,
                "live_score": live_score,
                "live_label": live_label,
                "is_match": is_match,
                "sim_score": sim_score,
                "feature": feature,
                "face_raw": face,
            })

        return annotated, results

