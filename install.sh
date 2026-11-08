#!/usr/bin/env bash
# Script tự động cài đặt môi trường hệ thống cho Raspberry Pi (Debian / Pi OS Bookworm & Bullseye)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================================="
echo "📦 BẮT ĐẦU CÀI ĐẶT HỆ THỐNG SMART LOCKER TRÊN RASPBERRY PI"
echo "=========================================================="

# 1. Cài đặt các thư viện hệ thống cần thiết cho OpenCV, Camera và GPIO (lgpio, swig)
echo "👉 Cập nhật và cài đặt thư viện hệ thống (libgl1, v4l-utils, python3-lgpio, swig)..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq || true
    sudo apt-get install -y \
        python3-dev \
        python3-venv \
        python3-pip \
        swig \
        python3-lgpio \
        python3-gpiozero \
        python3-smbus \
        i2c-tools \
        libgl1 \
        libglib2.0-0 \
        curl \
        v4l-utils
fi

# 2. Tạo môi trường ảo Python (.venv) với cờ --system-site-packages để dùng trực tiếp lgpio của hệ thống
if [ ! -d ".venv" ]; then
    echo "👉 Khởi tạo Python virtualenv (.venv với --system-site-packages)..."
    python3 -m venv --system-site-packages .venv
else
    echo "✅ Môi trường ảo .venv đã tồn tại."
fi

# 3. Kích hoạt và cài đặt gói thư viện Python từ requirements.txt
echo "👉 Nâng cấp pip và cài đặt thư viện Python từ requirements.txt..."
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt

# 4. Tải các model AI (YuNet, SFace, MiniFASNet)
echo "👉 Kiểm tra và tải model AI..."
bash download_models.sh

# 5. Cấp quyền thực thi cho các file bash
chmod +x run.sh download_models.sh install.sh 2>/dev/null || true

# Tạo các thư mục dữ liệu
mkdir -p data data/faces

echo "=========================================================="
echo "🎉 CÀI ĐẶT HOÀN TẤT!"
echo "Để chạy hệ thống:"
echo "   ./run.sh"
echo "=========================================================="
