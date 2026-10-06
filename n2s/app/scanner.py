"""扫描 notes/ 目录：识别新增/变更/删除，维护数据库，并把待生成文件排入后台队列。"""
import asyncio
import hashlib
from pathlib import Path

from . import db
from .config import NOTES_DIR

# 支持的文件扩展名
EXTENSIONS = {".md", ".txt", ".markdown"}

# 后台生成队列
_generation_queue: asyncio.Queue = asyncio.Queue()
_generator_task: asyncio.Task | None = None


def _hash_content(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _title_from_path(path: Path) -> str:
    return path.stem


def _category_from_path(rel: Path) -> str:
    """分类 = 去掉文件名后的目录层级，用 / 连接。
    例：操作系统/第一章/PV操作.md → "操作系统/第一章"
       操作系统/PV操作.md       → "操作系统"
       设备管理.md              → "未分类"
    """
    if len(rel.parts) > 1:
        return "/".join(rel.parts[:-1])
    return "未分类"


def _read_text(path: Path) -> str:
    """读取文本，容错编码（UTF-8 优先，失败退 GBK）。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def scan_once() -> list[int]:
    """扫描一次，返回本次新增/变更需要生成的 file id 列表。"""
    try:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # 只读挂载（如 Docker 卷 :ro）下目录已存在即可，忽略
        pass

    seen: set[str] = set()
    changed_ids: list[int] = []

    for f in sorted(NOTES_DIR.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in EXTENSIONS:
            continue
        rel = f.relative_to(NOTES_DIR)
        rel_str = rel.as_posix()
        seen.add(rel_str)

        title = _title_from_path(f)
        category = _category_from_path(rel)
        content_hash = _hash_content(f)

        existing = db.get_file_by_path(rel_str)
        if existing is None or existing["content_hash"] != content_hash:
            fid = db.upsert_file(rel_str, title, category, content_hash)
            changed_ids.append(fid)

    # 删除数据库中已不存在于磁盘的文件
    for row in db.all_files():
        if row["rel_path"] not in seen:
            db.delete_file(row["rel_path"])

    return changed_ids


async def _generator_loop():
    """串行消费生成队列。"""
    while True:
        fid, rel_path = await _generation_queue.get()
        try:
            p = NOTES_DIR / rel_path
            if not p.exists():
                continue  # 文件已被删，跳过
            raw_text = _read_text(p)
            from .pipeline import generate_file_safe
            await generate_file_safe(fid, raw_text, rel_path)
        except Exception:
            db.set_status(fid, "failed")
        finally:
            _generation_queue.task_done()


def ensure_generator():
    global _generator_task
    if _generator_task is None or _generator_task.done():
        _generator_task = asyncio.create_task(_generator_loop())


def enqueue(fid: int, rel_path: str):
    _generation_queue.put_nowait((fid, rel_path))


async def periodic_scan():
    """每 SCAN_INTERVAL_SEC 扫描一次，把变更排入队列。"""
    from .config import SCAN_INTERVAL_SEC
    while True:
        await asyncio.sleep(SCAN_INTERVAL_SEC)
        changed = scan_once()
        for fid in changed:
            row = db.get_file(fid)
            if row:
                enqueue(fid, row["rel_path"])


def scan_and_enqueue() -> list[int]:
    """手动/启动扫描：扫描并把变更立即排入队列。"""
    changed = scan_once()
    for fid in changed:
        row = db.get_file(fid)
        if row:
            enqueue(fid, row["rel_path"])
    return changed
