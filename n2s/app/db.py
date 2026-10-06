"""SQLite 访问层：建表 + 全部读写函数。使用标准库 sqlite3，不引入 ORM。"""
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  rel_path     TEXT UNIQUE NOT NULL,
  title        TEXT NOT NULL,
  category     TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status       TEXT DEFAULT 'pending',
  audio_path   TEXT,
  duration     REAL,
  updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS segments (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  idx       INTEGER NOT NULL,
  text      TEXT NOT NULL,
  start_sec REAL NOT NULL,
  end_sec   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS progress (
  file_id     INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  position_sec REAL DEFAULT 0,
  finished    INTEGER DEFAULT 0,
  updated_at  TEXT
);
"""

# 每线程一个连接，避免 SQLite 跨线程报错
_local = threading.local()


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def init_db():
    c = _conn()
    c.executescript(SCHEMA)
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- files ----------

def upsert_file(rel_path: str, title: str, category: str, content_hash: str) -> int:
    c = _conn()
    row = c.execute("SELECT id FROM files WHERE rel_path = ?", (rel_path,)).fetchone()
    if row:
        fid = row["id"]
        c.execute(
            """UPDATE files SET title=?, category=?, content_hash=?, status='pending',
               audio_path=NULL, duration=NULL, updated_at=? WHERE id=?""",
            (title, category, content_hash, _now(), fid),
        )
        # 内容变化 → 清理旧 segments 与进度
        c.execute("DELETE FROM segments WHERE file_id = ?", (fid,))
        c.execute("DELETE FROM progress WHERE file_id = ?", (fid,))
    else:
        cur = c.execute(
            """INSERT INTO files (rel_path, title, category, content_hash, status, updated_at)
               VALUES (?,?,?,?,'pending',?)""",
            (rel_path, title, category, content_hash, _now()),
        )
        fid = cur.lastrowid
    c.commit()
    return fid


def delete_file(rel_path: str):
    c = _conn()
    c.execute("DELETE FROM files WHERE rel_path = ?", (rel_path,))
    c.commit()


def get_file(fid: int):
    c = _conn()
    return c.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()


def get_file_by_path(rel_path: str):
    c = _conn()
    return c.execute("SELECT * FROM files WHERE rel_path = ?", (rel_path,)).fetchone()


def all_files():
    c = _conn()
    return c.execute("SELECT * FROM files ORDER BY category, title").fetchall()


def set_status(fid: int, status: str, audio_path: str | None = None, duration: float | None = None):
    c = _conn()
    c.execute(
        "UPDATE files SET status=?, audio_path=COALESCE(?,audio_path), duration=COALESCE(?,duration), updated_at=? WHERE id=?",
        (status, audio_path, duration, _now(), fid),
    )
    c.commit()


# ---------- segments ----------

def replace_segments(fid: int, segs: list[dict]):
    """segs: [{'idx': int, 'text': str, 'start_sec': float, 'end_sec': float}]"""
    c = _conn()
    c.execute("DELETE FROM segments WHERE file_id = ?", (fid,))
    c.executemany(
        "INSERT INTO segments (file_id, idx, text, start_sec, end_sec) VALUES (?,?,?,?,?)",
        [(fid, s["idx"], s["text"], s["start_sec"], s["end_sec"]) for s in segs],
    )
    c.commit()


def get_segments(fid: int):
    c = _conn()
    return c.execute(
        "SELECT * FROM segments WHERE file_id = ? ORDER BY idx", (fid,)
    ).fetchall()


# ---------- progress ----------

def get_progress(fid: int) -> dict:
    c = _conn()
    r = c.execute("SELECT * FROM progress WHERE file_id = ?", (fid,)).fetchone()
    if r is None:
        return {"position_sec": 0.0, "finished": 0}
    return {"position_sec": r["position_sec"], "finished": r["finished"]}


def set_progress(fid: int, position_sec: float, finished: int):
    c = _conn()
    c.execute(
        """INSERT INTO progress (file_id, position_sec, finished, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(file_id) DO UPDATE SET
             position_sec=excluded.position_sec,
             finished=excluded.finished,
             updated_at=excluded.updated_at""",
        (fid, position_sec, finished, _now()),
    )
    c.commit()


def reset_progress(fid: int):
    c = _conn()
    c.execute("DELETE FROM progress WHERE file_id = ?", (fid,))
    c.commit()
