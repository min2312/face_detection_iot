import os
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODELS = {
    "face_detection_yunet_2023mar.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    "MiniFASNetV2.onnx": "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx",
}


def download_file(url: str, dest_path: Path):
    if dest_path.exists() and dest_path.stat().st_size > 10000:
        print(f"✅ Đã có sẵn: {dest_path.name} ({dest_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return

    print(f"⏳ Đang tải {dest_path.name} từ:\n   {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req) as resp, open(dest_path, "wb") as f:
            total_size = int(resp.info().get("Content-Length", 0))
            downloaded = 0
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = downloaded / total_size * 100
                    print(f"\r   [{percent:5.1f}%] {downloaded/1024/1024:.2f}/{total_size/1024/1024:.2f} MB", end="")
            print()
        print(f"✅ Tải thành công: {dest_path.name} ({dest_path.stat().st_size / 1024 / 1024:.2f} MB)")
    except Exception as e:
        print(f"❌ Lỗi khi tải {dest_path.name}: {e}")
        if dest_path.exists():
            dest_path.unlink()
        raise


def main():
    print("=" * 60)
    print("🚀 BẮT ĐẦU TẢI CÁC MODEL AI CHO HỆ THỐNG SMART LOCKER")
    print("=" * 60)
    for filename, url in MODELS.items():
        dest = MODELS_DIR / filename
        download_file(url, dest)
    print("=" * 60)
    print("🎉 TẤT CẢ MODEL ĐÃ SẴN SÀNG TRONG THƯ MỤC 'models/'!")
    print("=" * 60)


if __name__ == "__main__":
    main()

