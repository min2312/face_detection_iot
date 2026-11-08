"""
recognition.py - Module phối hợp: YuNet (Detection) + AntiSpoof (Liveness) + SFace (Recognition)
Thiết kế Thread-Safe và Đơn luồng xử lý AI để chống nghẽn CPU và chống crash đen màn hình trên Raspberry Pi.
"""

from pathlib import Path
import threading
import time
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
            raise FileNotFoundError(f"Thiếu file model ONNX trong thư mục '{models_dir}'.")

        # Khóa Lock để đảm bảo an toàn đa luồng (OpenCV C++ DNN KHÔNG an toàn nếu gọi song song)
        self._dnn_lock = threading.Lock()

        # Giới hạn số thread OpenCV để không tranh CPU với Pi
        cv2.setNumThreads(2)
        self.detector = cv2.FaceDetectorYN.create(
            str(det_path), "", (320, 240), 0.75, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(rec_path), "")
        self.anti_spoof = AntiSpoofDetector(str(anti_path), threshold=liveness_threshold)

        self.sim_threshold = sim_threshold
        self.liveness_threshold = liveness_threshold

        # Bộ đệm chia sẻ kết quả cho Flask và LockerManager
        self.latest_jpeg: Optional[bytes] = None
        self.latest_analysis: Optional[dict] = None
        self._cache_lock = threading.Lock()

    def detect_faces(self, frame: np.ndarray) -> np.ndarray:
        """Phát hiện khuôn mặt trên frame bằng YuNet (Thread-safe)."""
        with self._dnn_lock:
            h, w = frame.shape[:2]
            self.detector.setInputSize((w, h))
            _, faces = self.detector.detect(frame)
            return np.empty((0, 15), dtype=np.float32) if faces is None else faces

    def extract_feature(self, frame: np.ndarray, face: np.ndarray) -> np.ndarray:
        """Trích xuất vector đặc trưng 128 chiều bằng SFace (Thread-safe)."""
        with self._dnn_lock:
            aligned = self.recognizer.alignCrop(frame, face)
            feature = self.recognizer.feature(aligned)
            return feature

    def compute_similarity(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """Tính độ tương đồng Cosine giữa 2 vector khuôn mặt (Thread-safe)."""
        with self._dnn_lock:
            score = self.recognizer.match(
                feat1.reshape(1, -1),
                feat2.reshape(1, -1),
                cv2.FaceRecognizerSF_FR_COSINE
            )
            return float(score)

    def process_and_cache_frame(
        self,
        frame: np.ndarray,
        is_active_scanning: bool = False,
        target_embedding: Optional[np.ndarray] = None,
        target_name: str = "",
        system_status_text: str = "IDLE"
    ) -> bytes:
        """
        Hàm xử lý TẬP TRUNG duy nhất:
        - Đọc frame
        - Phát hiện khuôn mặt
        - Phân tích Liveness & Nhận diện (nếu đang quét)
        - Vẽ thông tin trực quan
        - Nén JPEG và lưu cache cho tất cả các luồng dùng chung (Tránh crash đen màn hình).
        """
        annotated = frame.copy()
        faces = self.detect_faces(frame)
        analysis_result = {
            "has_face": False,
            "is_real": False,
            "live_score": 0.0,
            "live_label": "",
            "is_match": False,
            "sim_score": 0.0,
            "feature": None,
            "raw_frame": frame.copy(),
        }

        if len(faces) > 0:
            analysis_result["has_face"] = True
            face = faces[0]  # Lấy khuôn mặt rõ nhất
            bbox = [int(v) for v in face[:4]]
            x, y, w, h = bbox

            if not is_active_scanning:
                # ── TRẠNG THÁI CHỜ (IDLE): Chỉ vẽ viền xanh dương nhẹ nhàng, KHÔNG chạy chống giả mạo
                color = (255, 200, 0)
                label_text = "👤 San sang (Bam Cat do / Lay do)"
                cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
                cv2.putText(annotated, label_text, (x, max(25, y - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
            else:
                # ── TRẠNG THÁI QUÉT MẶT (CẤT ĐỒ HOẶC LẤY ĐỒ)
                with self._dnn_lock:
                    is_real, live_score, live_label = self.anti_spoof.check_liveness(frame, bbox)

                analysis_result["is_real"] = is_real
                analysis_result["live_score"] = live_score
                analysis_result["live_label"] = live_label

                if is_real:
                    feature = self.extract_feature(frame, face)
                    analysis_result["feature"] = feature

                    if target_embedding is not None:
                        sim_score = self.compute_similarity(feature, target_embedding)
                        is_match = (sim_score >= self.sim_threshold)
                        analysis_result["sim_score"] = sim_score
                        analysis_result["is_match"] = is_match

                        if is_match:
                            color = (0, 255, 0)  # Xanh lá
                            label_text = f"✅ {target_name} ({sim_score:.2f}) [REAL]"
                        else:
                            color = (0, 165, 255)  # Cam
                            label_text = f"❌ Sai nguoi ({sim_score:.2f}) [REAL]"
                    else:
                        color = (0, 255, 0)  # Xanh lá
                        label_text = f"👤 Nguoi that ({live_score*100:.0f}%)"
                else:
                    # Giả mạo
                    color = (0, 0, 255)  # Đỏ
                    label_text = f"🚨 SPOOF ({live_label} {live_score*100:.0f}%)"

                cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
                cv2.putText(annotated, label_text, (x, max(25, y - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # Vẽ thanh tiêu đề trạng thái góc trên
        h_f, w_f = annotated.shape[:2]
        banner = annotated.copy()
        cv2.rectangle(banner, (0, 0), (w_f, 36), (20, 20, 20), -1)
        cv2.addWeighted(banner, 0.75, annotated, 0.25, 0, annotated)
        cv2.putText(annotated, f"Trang thai: {system_status_text}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # Nén JPEG an toàn
        ret, jpeg = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
        jpeg_bytes = jpeg.tobytes() if ret else b""

        with self._cache_lock:
            self.latest_jpeg = jpeg_bytes
            self.latest_analysis = analysis_result

        return jpeg_bytes

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._cache_lock:
            return self.latest_jpeg

    def get_latest_analysis(self) -> Optional[dict]:
        with self._cache_lock:
            return self.latest_analysis
