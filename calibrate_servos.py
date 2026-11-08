#!/usr/bin/env python3
"""
calibrate_servos.py - Công cụ căn chỉnh góc quay cho 4 Servo (Hỗ trợ cả chiều thuận & chiều nghịch)
- Cho phép chỉnh riêng Góc Mở (UNLOCK_ANGLE) và Góc Đóng (LOCK_ANGLE) cho từng tủ.
- Tủ chiều thuận (quay lên): Đóng ở 0°, Mở ở 120°
- Tủ chiều nghịch (quay xuống): Đóng ở 120°, Mở ở 0° (hoặc Đóng ở 180°, Mở ở 60°)
Tự động lưu vào file .env cho toàn bộ hệ thống sử dụng.
"""

import argparse
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
env_file = BASE_DIR / ".env"

if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v

PCA_ADDR = int(os.environ.get("PCA_ADDR", "0x40"), 16)
PCA_BUS = int(os.environ.get("PCA_BUS", "1"))

# Kênh 4 servo
CHANNELS = {
    1: int(os.environ.get("SERVO_1_CHANNEL", "0")),
    2: int(os.environ.get("SERVO_2_CHANNEL", "1")),
    3: int(os.environ.get("SERVO_3_CHANNEL", "2")),
    4: int(os.environ.get("SERVO_4_CHANNEL", "3")),
}

# Góc đóng khóa (mặc định 0°, nếu ngược chiều có thể là 120° hoặc 180°)
LOCK_ANGLES = {
    1: float(os.environ.get("SERVO_1_LOCK_ANGLE", "0")),
    2: float(os.environ.get("SERVO_2_LOCK_ANGLE", "0")),
    3: float(os.environ.get("SERVO_3_LOCK_ANGLE", "0")),
    4: float(os.environ.get("SERVO_4_LOCK_ANGLE", "0")),
}

# Góc mở khóa (mặc định 120° nếu thuận, hoặc 0° nếu nghịch)
UNLOCK_ANGLES = {
    1: float(os.environ.get("SERVO_1_UNLOCK_ANGLE", "120")),
    2: float(os.environ.get("SERVO_2_UNLOCK_ANGLE", "120")),
    3: float(os.environ.get("SERVO_3_UNLOCK_ANGLE", "120")),
    4: float(os.environ.get("SERVO_4_UNLOCK_ANGLE", "120")),
}

# Khởi tạo thư viện Adafruit ServoKit
try:
    from adafruit_servokit import ServoKit
    kit = ServoKit(channels=16, address=PCA_ADDR)
    IS_SIMULATION = False
except Exception as e:
    print(f"⚠️ Không thể kết nối phần cứng PCA9685 ({e}). Đang chạy chế độ mô phỏng.")
    kit = None
    IS_SIMULATION = True


def set_servo(channel: int, angle: float):
    """Quay servo ở kênh `channel` tới góc `angle` (0° đến 180°)."""
    angle = max(0, min(180, int(angle)))
    if kit is not None:
        try:
            kit.servo[channel].angle = angle
        except Exception as err:
            print(f"❌ Lỗi điều khiển kênh {channel}: {err}")
    else:
        print(f"   [Mô phỏng] Servo kênh {channel} -> Góc {angle}°")


def reset_all_to_locked():
    """Đưa toàn bộ 4 servo về góc khóa an toàn (LOCK_ANGLE)."""
    print("\n🔒 Đang đưa toàn bộ 4 Servo về góc ĐÓNG KHÓA an toàn...")
    for lid, ch in CHANNELS.items():
        ang = LOCK_ANGLES[lid]
        set_servo(ch, ang)
        time.sleep(0.05)
    print("✅ Toàn bộ 4 Servo đã được khóa an toàn.\n")


def update_env_variable(key: str, value: str):
    """Cập nhật hoặc thêm một biến cấu hình vào file .env."""
    if not env_file.exists():
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")
        return

    lines = []
    found = False
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"# {key}="):
                lines.append(f"{key}={value}\n")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key}={value}\n")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)


def print_banner():
    print("=" * 70)
    print("🛠️  CÔNG CỤ CĂN CHỈNH GÓC QUAY 4 SERVO (HỖ TRỢ CHIỀU NGHỊCH)")
    print(f"📡 Địa chỉ I2C: 0x{PCA_ADDR:02X} | Bus: {PCA_BUS}")
    print("-" * 70)
    print(f"{'TỦ SỐ':<8} | {'KÊNH':<6} | {'GÓC ĐÓNG (LOCK)':<18} | {'GÓC MỞ (UNLOCK)':<18} | {'HƯỚNG QUAY'}")
    print("-" * 70)
    for lid in range(1, 5):
        ch = CHANNELS[lid]
        l_ang = LOCK_ANGLES[lid]
        u_ang = UNLOCK_ANGLES[lid]
        direction = "Thuận (Tăng góc)" if u_ang >= l_ang else "Nghịch (Giảm góc)"
        print(f"Tủ {lid:<5} | Ch{ch:<4} | {l_ang:<4}°              | {u_ang:<4}°              | {direction}")
    print("=" * 70)


def test_single_locker(lid: int):
    """Test và tinh chỉnh góc quay mở & đóng cho 1 tủ cụ thể."""
    ch = CHANNELS[lid]
    cur_lock = LOCK_ANGLES[lid]
    cur_unlock = UNLOCK_ANGLES[lid]

    print(f"\n👉 [TỦ SỐ {lid}] (PCA9685 Kênh {ch})")
    print(f"   Cấu hình hiện tại: Góc Đóng = {cur_lock}°, Góc Mở = {cur_unlock}°")
    print("-" * 50)
    print("💡 MẸO:")
    print("   - Nếu lắp chiều THUẬN: Đóng = 0°, Mở = 120°")
    print("   - Nếu lắp chiều NGHỊCH (đi xuống): Đóng = 120°, Mở = 0° (hoặc Đóng = 180°, Mở = 60°)")
    print("-" * 50)

    val_open = input(f"   Nhập GÓC MỞ muốn thử (0 - 180°, mặc định {cur_unlock}): ").strip()
    try:
        test_open = float(val_open) if val_open else cur_unlock
    except ValueError:
        print("❌ Góc không hợp lệ!")
        return

    val_lock = input(f"   Nhập GÓC ĐÓNG muốn thử (0 - 180°, mặc định {cur_lock}): ").strip()
    try:
        test_lock = float(val_lock) if val_lock else cur_lock
    except ValueError:
        print("❌ Góc không hợp lệ!")
        return

    test_open = max(0.0, min(180.0, test_open))
    test_lock = max(0.0, min(180.0, test_lock))

    print(f"\n🔓 [Tủ {lid}] Đang QUAY MỞ tới góc {test_open}°...")
    set_servo(ch, test_open)
    print("   👉 Đang giữ chốt mở trong 3.5 giây để bạn kiểm tra cơ khí...")
    time.sleep(3.5)

    print(f"🔒 [Tủ {lid}] Đang QUAY ĐÓNG về góc {test_lock}°...")
    set_servo(ch, test_lock)
    time.sleep(0.5)

    save_choice = input(f"\n❓ Bạn có muốn lưu: Đóng={test_lock}°, Mở={test_open}° cho TỦ {lid} vào .env không? (y/N): ").strip().lower()
    if save_choice in ("y", "yes"):
        LOCK_ANGLES[lid] = test_lock
        UNLOCK_ANGLES[lid] = test_open
        os.environ[f"SERVO_{lid}_LOCK_ANGLE"] = str(test_lock)
        os.environ[f"SERVO_{lid}_UNLOCK_ANGLE"] = str(test_open)

        v_lock = str(int(test_lock) if test_lock.is_integer() else test_lock)
        v_open = str(int(test_open) if test_open.is_integer() else test_open)
        update_env_variable(f"SERVO_{lid}_LOCK_ANGLE", v_lock)
        update_env_variable(f"SERVO_{lid}_UNLOCK_ANGLE", v_open)
        print(f"💾 Đã lưu thành công vào .env: SERVO_{lid}_LOCK_ANGLE={v_lock}, SERVO_{lid}_UNLOCK_ANGLE={v_open}!")


def test_all_lockers_sequence():
    """Chạy thử mở lần lượt cả 4 tủ theo góc cấu hình rồi đóng lại."""
    print("\n🚀 Đang chạy thử mở lần lượt cả 4 tủ theo cấu hình:")
    for lid in range(1, 5):
        ch = CHANNELS[lid]
        u_ang = UNLOCK_ANGLES[lid]
        l_ang = LOCK_ANGLES[lid]
        print(f"👉 Mở Tủ {lid} (Kênh {ch} -> Góc Mở {u_ang}°)...")
        set_servo(ch, u_ang)
        time.sleep(2.0)
        print(f"   Đóng Tủ {lid} (Kênh {ch} -> Góc Đóng {l_ang}°)...")
        set_servo(ch, l_ang)
        time.sleep(0.5)
    print("✅ Đã hoàn tất kiểm tra cả 4 tủ!\n")


def interactive_menu():
    """Menu tương tác trực quan qua terminal."""
    reset_all_to_locked()

    while True:
        print_banner()
        print("👉 CHỌN THAO TÁC:")
        print("  [1] Tinh chỉnh Tủ 1")
        print("  [2] Tinh chỉnh Tủ 2")
        print("  [3] Tinh chỉnh Tủ 3")
        print("  [4] Tinh chỉnh Tủ 4")
        print("  [A] Thử mở lần lượt CẢ 4 TỦ (theo góc đã cấu hình)")
        print("  [Z] Khóa toàn bộ 4 Tủ về vị trí ĐÓNG")
        print("  [Q] Thoát")
        print("-" * 70)

        choice = input("👉 Nhập lựa chọn của bạn: ").strip().upper()

        if choice in ("1", "2", "3", "4"):
            test_single_locker(int(choice))
            input("\nẤn Enter để tiếp tục...")
        elif choice == "A":
            test_all_lockers_sequence()
            input("\nẤn Enter để tiếp tục...")
        elif choice == "Z":
            reset_all_to_locked()
            input("\nẤn Enter để tiếp tục...")
        elif choice == "Q":
            reset_all_to_locked()
            print("👋 Đã thoát công cụ căn chỉnh servo. Tạm biệt!")
            break
        else:
            print("❌ Lựa chọn không hợp lệ, vui lòng thử lại!")
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Công cụ căn chỉnh góc Servo cho 4 Tủ")
    parser.add_argument("--locker", type=int, choices=[1, 2, 3, 4], help="Số thứ tự tủ muốn test (1-4)")
    parser.add_argument("--open-angle", type=float, help="Góc mở muốn test (0-180)")
    parser.add_argument("--lock-angle", type=float, help="Góc đóng muốn test (0-180)")
    parser.add_argument("--lock-all", action="store_true", help="Đưa tất cả 4 servo về góc đóng")
    parser.add_argument("--all", action="store_true", help="Test mở lần lượt cả 4 tủ")
    args = parser.parse_args()

    if args.lock_all:
        reset_all_to_locked()
        return

    if args.all:
        test_all_lockers_sequence()
        return

    if args.locker:
        ch = CHANNELS[args.locker]
        u_ang = args.open_angle if args.open_angle is not None else UNLOCK_ANGLES[args.locker]
        l_ang = args.lock_angle if args.lock_angle is not None else LOCK_ANGLES[args.locker]
        print(f"👉 Mở Tủ {args.locker} (Kênh {ch}) tới góc {u_ang}°...")
        set_servo(ch, u_ang)
        time.sleep(3.0)
        print(f"🔒 Đóng Tủ {args.locker} về góc {l_ang}°...")
        set_servo(ch, l_ang)
        return

    try:
        interactive_menu()
    except KeyboardInterrupt:
        print("\n\n🔒 Đang ngắt, đưa tất cả servo về góc đóng...")
        reset_all_to_locked()
        print("👋 Thoát.")


if __name__ == "__main__":
    main()
