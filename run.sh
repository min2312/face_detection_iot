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

# Cấu hình chân GPIO mặc định (có thể thay đổi tại đây hoặc truyền qua biến môi trường)
export SERVO_PIN="${SERVO_PIN:-18}"
export DOOR_SENSOR_PIN="${DOOR_SENSOR_PIN:-23}"
export RED_LED_PIN="${RED_LED_PIN:-17}"
export GREEN_LED_PIN="${GREEN_LED_PIN:-27}"
export CAMERA_DEVICE="${CAMERA_DEVICE:-0}"
export PORT="${PORT:-5000}"

echo "=========================================================="
echo "🚀 KHỞI ĐỘNG HỆ THỐNG SMART LOCKER IOT"
echo "📷 Camera Device     : $CAMERA_DEVICE"
echo "⚙️  Servo Pin (Lock)  : GPIO $SERVO_PIN"
echo "🧲 Cảm biến từ MC-38 : GPIO $DOOR_SENSOR_PIN"
echo "🔴 Red LED Pin       : GPIO $RED_LED_PIN"
echo "🟢 Green LED Pin     : GPIO $GREEN_LED_PIN"
echo "🌐 Web Server Port   : $PORT"
echo "=========================================================="

MY_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo "👉 Truy cập Web Kiosk  : http://${MY_IP}:${PORT}"
echo "👉 Truy cập Trang Admin: http://${MY_IP}:${PORT}/admin"
echo "=========================================================="

exec .venv/bin/python app.py

