#!/usr/bin/env bash
# Script tự động cài đặt môi trường hệ thống cho Raspberry Pi (Debian / Pi OS Bookworm & Bullseye)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "=========================================================="
echo "📦 BẮT ĐẦU CÀI ĐẶT HỆ THỐNG SMART LOCKER TRÊN RASPBERRY PI"
echo "=========================================================="

# 1. Cài đặt các thư viện hệ thống cần thiết cho OpenCV và Camera
echo "👉 Cập nhật và cài đặt thư viện hệ thống (libgl1, v4l-utils, curl)..."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq || true
    sudo apt-get install -y -qq \
        python3-dev \
        python3-venv \
        python3-pip \
        libgl1 \
        libglib2.0-0 \
        curl \
        v4l-utils \
        libcap-dev
fi

# 2. Tạo môi trường ảo Python (.venv)
if [ ! -d ".venv" ]; then
    echo "👉 Khởi tạo Python virtualenv (.venv)..."
    python3 -m venv .venv
else
    echo "✅ Môi trường ảo .venv đã tồn tại."
fi

# 3. Kích hoạt và cài đặt gói thư viện Python
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

