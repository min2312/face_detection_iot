"""
database.py - Quản lý cơ sở dữ liệu SQLite cho Hệ thống Smart Locker (Hỗ trợ 4 Ngăn Tủ)
Lưu trữ thông tin 4 ngăn tủ, vector khuôn mặt người gửi đồ, lịch sử đóng/mở và ảnh log.
"""

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import List, Optional, Tuple
import numpy as np


class LockerDatabase:
    def __init__(self, db_dir: str = None):
        if db_dir is None:
            base_dir = Path(__file__).resolve().parent
            db_dir = str(base_dir / "data")

        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.faces_dir = self.db_dir / "faces"
        self.faces_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.db_dir / "locker.db"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cur = conn.cursor()

            # Bảng quản lý 4 ngăn tủ độc lập
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lockers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'AVAILABLE', -- 'AVAILABLE', 'OCCUPIED'
                    occupant_name TEXT,
                    occupant_embedding BLOB,
                    photo_path TEXT,
                    deposit_time TIMESTAMP
                )
            """)

            # Bảng nhật ký hoạt động (Audit Logs)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL, -- 'DEPOSIT', 'WITHDRAW', 'SPOOF_DEPOSIT', 'SPOOF_WITHDRAW', 'UNAUTHORIZED', 'ADMIN_UNLOCK'
                    locker_id INTEGER,
                    user_name TEXT,
                    similarity REAL DEFAULT 0.0,
                    liveness_score REAL DEFAULT 0.0,
                    photo_path TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    note TEXT
                )
            """)

            # Bảng tài khoản admin
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )
            """)

            # Khởi tạo 4 ngăn tủ mặc định (Tủ số 1 đến Tủ số 4)
            for i in range(1, 5):
                cur.execute("SELECT COUNT(*) FROM lockers WHERE id = ?", (i,))
                if cur.fetchone()[0] == 0:
                    cur.execute(
                        "INSERT INTO lockers (id, name, status) VALUES (?, ?, 'AVAILABLE')",
                        (i, f"Tủ số {i}")
                    )

            # Khởi tạo tài khoản admin mặc định: admin / admin123
            cur.execute("SELECT COUNT(*) FROM admin_users WHERE username = 'admin'")
            if cur.fetchone()[0] == 0:
                cur.execute(
                    "INSERT INTO admin_users (username, password) VALUES ('admin', 'admin123')"
                )

            conn.commit()

    # ── QUẢN LÝ 4 NGĂN TỦ ────────────────────────────────────────────────

    def get_locker(self, locker_id: int) -> dict:
        """Lấy thông tin chi tiết một ngăn tủ theo ID."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM lockers WHERE id = ?", (locker_id,))
            row = cur.fetchone()
            if not row:
                return {}
            data = dict(row)
            if data.get("occupant_embedding"):
                data["embedding"] = np.frombuffer(data["occupant_embedding"], dtype=np.float32)
            else:
                data["embedding"] = None
            return data

    def get_all_lockers(self) -> List[dict]:
        """Lấy danh sách cả 4 ngăn tủ."""
        lockers = []
        for i in range(1, 5):
            lockers.append(self.get_locker(i))
        return lockers

    def get_first_available_locker(self) -> Optional[dict]:
        """Tìm ngăn tủ trống đầu tiên (Tủ 1 -> 4)."""
        for i in range(1, 5):
            l = self.get_locker(i)
            if l.get("status") == "AVAILABLE":
                return l
        return None

    def find_occupied_locker_by_face(
        self,
        engine,
        feature: np.ndarray,
        threshold: Optional[float] = None
    ) -> Tuple[Optional[dict], float]:
        """
        Tự động so khớp vector khuôn mặt với TẤT CẢ các ngăn tủ đang có người gửi.
        Trả về (ngăn_tủ_khớp, điểm_tương_đồng).
        """
        if threshold is None:
            threshold = getattr(engine, "sim_threshold", 0.50)

        best_locker = None
        best_score = -1.0

        for i in range(1, 5):
            l = self.get_locker(i)
            if l.get("status") == "OCCUPIED" and l.get("embedding") is not None:
                score = engine.compute_similarity(feature, l["embedding"])
                if score > best_score:
                    best_score = score
                    if score >= threshold:
                        best_locker = l

        return best_locker, best_score

    def occupy_locker(
        self,
        locker_id: int,
        name: str,
        embedding: np.ndarray,
        photo_path: str = None
    ) -> bool:
        """Gán người gửi vào ngăn tủ và chuyển trạng thái sang OCCUPIED."""
        emb_bytes = embedding.astype(np.float32).tobytes()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE lockers
                SET status = 'OCCUPIED',
                    occupant_name = ?,
                    occupant_embedding = ?,
                    photo_path = ?,
                    deposit_time = ?
                WHERE id = ?
            """, (name, emb_bytes, photo_path, now, locker_id))
            conn.commit()
            return cur.rowcount > 0

    def release_locker(self, locker_id: int) -> bool:
        """Giải phóng ngăn tủ sau khi người dùng lấy đồ xong."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE lockers
                SET status = 'AVAILABLE',
                    occupant_name = NULL,
                    occupant_embedding = NULL,
                    photo_path = NULL,
                    deposit_time = NULL
                WHERE id = ?
            """, (locker_id,))
            conn.commit()
            return cur.rowcount > 0

    # ── NHẬT KÝ HOẠT ĐỘNG (AUDIT LOGS) ──────────────────────────────────

    def log_event(
        self,
        event_type: str,
        locker_id: int = 1,
        user_name: str = "",
        similarity: float = 0.0,
        liveness_score: float = 0.0,
        photo_path: str = None,
        note: str = ""
    ):
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO audit_logs (
                    event_type, locker_id, user_name, similarity,
                    liveness_score, photo_path, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (event_type, locker_id, user_name, similarity, liveness_score, photo_path, note))
            conn.commit()

    def get_recent_logs(self, limit: int = 50) -> list:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, event_type, locker_id, user_name, similarity,
                       liveness_score, photo_path, timestamp, note
                FROM audit_logs
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

    def clear_logs(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM audit_logs")
            conn.commit()

    # ── QUẢN LÝ ADMIN ────────────────────────────────────────────────────

    def verify_admin(self, username: str, password: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT password FROM admin_users WHERE username = ?", (username,)
            )
            row = cur.fetchone()
            if row and row["password"] == password:
                return True
        return False

    def change_admin_password(self, username: str, new_password: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE admin_users SET password = ? WHERE username = ?",
                (new_password, username)
            )
            conn.commit()
            return cur.rowcount > 0
