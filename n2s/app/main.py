"""FastAPI 入口：路由、静态挂载、生命周期管理。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, scanner
from .config import CACHE_DIR, NOTES_DIR, BASE_DIR


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
