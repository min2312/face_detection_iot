#!/usr/bin/env bash
# Script tải 3 model AI cho Raspberry Pi / Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p models

echo "=========================================================="
echo "🚀 ĐANG TẢI MODEL AI (YuNet, SFace, MiniFASNet Anti-Spoof)"
echo "=========================================================="

download_file() {
    local url="$1"
    local output="$2"

    if [ -f "$output" ] && [ $(stat -c%s "$output" 2>/dev/null || stat -f%z "$output" 2>/dev/null) -gt 10000 ]; then
        echo "✅ Đã tồn tại: $output"
        return 0
    fi

    echo "⏳ Đang tải: $output ..."
    if command -v curl >/dev/null 2>&1; then
        curl -L --fail --retry 3 -o "$output" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "$output" "$url"
    else
        echo "❌ Cần cài đặt curl hoặc wget!" >&2
        exit 1
    fi
    echo "✅ Tải thành công: $output"
}

# 1. YuNet (Face Detection)
download_file \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
    "models/face_detection_yunet_2023mar.onnx"

# 2. SFace (Face Recognition)
download_file \
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
    "models/face_recognition_sface_2021dec.onnx"

# 3. MiniFASNetV2 (Face Anti-Spoofing / Liveness)
download_file \
    "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx" \
    "models/MiniFASNetV2.onnx"

echo "=========================================================="
echo "🎉 TẤT CẢ MODEL ĐÃ ĐƯỢC TẢI XONG TRONG models/ !"
echo "=========================================================="

