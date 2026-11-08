#!/usr/bin/env bash
# Script chạy hệ thống Smart Locker trên Raspberry Pi
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if [ ! -x ".venv/bin/python" ]; then
    echo "❌ Chưa có môi trường .venv! Vui lòng chạy './install.sh' trước." >&2
    exit 1
fi

# Đọc cấu hình từ file .env nếu có
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "📄 Đang đọc cấu hình từ .env ..."
    set -o allexport
    source "$PROJECT_DIR/.env"
    set +o allexport
fi

# Cấu hình Camera: Tự động ghép CAMERA_IP (Webcam laptop) hoặc dùng USB camera
if [ -n "${CAMERA_IP:-}" ]; then
    export CAMERA_DEVICE="http://${CAMERA_IP}:${CAMERA_PORT:-5000}${CAMERA_ENDPOINT:-/video}"
else
    export CAMERA_DEVICE="${CAMERA_DEVICE:-0}"
fi

export PORT="${PORT:-8080}"

echo "=========================================================="
echo "🚀 KHỞI ĐỘNG HỆ THỐNG SMART LOCKER IOT (4 NGĂN TỦ)"
if [ -n "${CAMERA_IP:-}" ]; then
    echo "📷 Camera Stream (Laptop) : $CAMERA_DEVICE"
else
    echo "📷 Camera USB Device      : $CAMERA_DEVICE"
fi
echo "⚙️  I2C PCA9685 Driver     : Bus ${PCA_BUS:-1}, Addr ${PCA_ADDR:-0x40}"
echo "🕹️  Servo Channels (4 Tủ)  : Tủ 1 -> Ch${SERVO_1_CHANNEL:-0}, Tủ 2 -> Ch${SERVO_2_CHANNEL:-1}, Tủ 3 -> Ch${SERVO_3_CHANNEL:-2}, Tủ 4 -> Ch${SERVO_4_CHANNEL:-3}"
echo "🧲 Cảm biến từ MC-38      : GPIO ${DOOR_1_PIN:-23}, ${DOOR_2_PIN:-24}, ${DOOR_3_PIN:-25}, ${DOOR_4_PIN:-26}"
echo "🔴 Red LED Pin            : GPIO ${RED_LED_PIN:-17}"
echo "🟢 Green LED Pin          : GPIO ${GREEN_LED_PIN:-27}"
echo "🌐 Web Server Port        : $PORT"
echo "=========================================================="

MY_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo "👉 Truy cập Web Kiosk  : http://${MY_IP}:${PORT}"
echo "👉 Truy cập Trang Admin: http://${MY_IP}:${PORT}/admin"
echo "=========================================================="

exec .venv/bin/python app.py

