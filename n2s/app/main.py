"""FastAPI 入口：路由、静态挂载、生命周期管理。"""
import asyncio
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, scanner
from .config import CACHE_DIR, NOTES_DIR, BASE_DIR

# 允许上传的扩展名（与扫描器一致）
ALLOWED_EXTENSIONS = {".md", ".txt", ".markdown"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scanner.ensure_generator()
    # 启动即扫描，并把待生成项排入队列
    scanner.scan_and_enqueue()
    periodic = asyncio.create_task(scanner.periodic_scan())
    yield
    periodic.cancel()


app = FastAPI(title="NoteToSpeech", lifespan=lifespan)

# 确保数据目录存在（Docker 挂载卷可能不预先创建这些子目录）
CACHE_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

# 静态资源
app.mount("/audio", StaticFiles(directory=str(CACHE_DIR)), name="audio")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class ProgressIn(BaseModel):
    position_sec: float
    finished: int = 0


def _file_summary(row):
    """把文件行转成前端需要的摘要。"""
    prog = db.get_progress(row["id"])
    duration = row["duration"] or 0
    pct = round(prog["position_sec"] / duration * 100) if duration > 0 else 0
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "status": row["status"],
        "duration": duration,
        "position_sec": prog["position_sec"],
        "finished": bool(prog["finished"]),
        "percent": pct,
        "audio_url": f"/audio/{row['audio_path']}" if row["audio_path"] else None,
    }


@app.get("/")
def index():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


@app.get("/api/library")
def library():
    files = db.all_files()
    return {"files": [_file_summary(r) for r in files]}


@app.get("/api/files/{fid}")
def file_detail(fid: int):
    row = db.get_file(fid)
    if row is None:
        raise HTTPException(404, "文件不存在")
    segs = db.get_segments(fid)
    return {
        **_file_summary(row),
        "segments": [
            {"idx": s["idx"], "text": s["text"], "start_sec": s["start_sec"], "end_sec": s["end_sec"]}
            for s in segs
        ],
    }


@app.post("/api/files/{fid}/progress")
def save_progress(fid: int, body: ProgressIn):
    row = db.get_file(fid)
    if row is None:
        raise HTTPException(404, "文件不存在")
    finished = 1 if body.finished else 0
    db.set_progress(fid, body.position_sec, finished)
    return {"ok": True}


@app.post("/api/scan")
def rescan():
    changed = scanner.scan_and_enqueue()
    return {"ok": True, "changed": changed}


def _safe_target_dir(target_dir: str) -> Path:
    """校验并返回安全的子目录路径，防止路径穿越（../ 等）。"""
    if not target_dir:
        return NOTES_DIR
    # 规范化，去除 .. 和绝对路径
    p = Path(target_dir)
    if p.is_absolute() or ".." in p.parts:
        raise HTTPException(400, "非法的目标目录")
    dest = (NOTES_DIR / p).resolve()
    # 确保最终路径仍在 notes 目录内
    if not str(dest).startswith(str(NOTES_DIR.resolve())):
        raise HTTPException(400, "非法的目标目录")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


@app.post("/api/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(""),
):
    """上传笔记文件到 notes 目录（可选子目录），保存后触发扫描。"""
    dest = _safe_target_dir(target_dir)

    saved = []
    skipped = []
    for f in files:
        filename = Path(f.filename or "").name  # 去除客户端可能带的路径
        if not filename:
            skipped.append({"name": f.filename, "reason": "空文件名"})
            continue
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            skipped.append({"name": filename, "reason": f"不支持的类型 {ext}"})
            continue

        out_path = dest / filename
        # 写入文件
        with open(out_path, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(filename)

    # 上传后立即触发扫描，让新文件进入生成队列
    changed = scanner.scan_and_enqueue()

    return {
        "ok": True,
        "saved": saved,
        "skipped": skipped,
        "changed": changed,
    }
