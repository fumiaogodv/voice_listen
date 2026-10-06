"""生成管线：分条 → 逐条 TTS → 探测时长 → 拼接成整文件 MP3 → 写库。

关键：segments 表的 start_sec/end_sec 来自每条音频的真实时长（mutagen 读取），
这是前端"歌词式同步"的精度来源，绝不估算。

ffmpeg 二进制来源：优先系统 PATH，否则回退到 imageio-ffmpeg 自带的静态二进制，
使本项目在无系统 ffmpeg 的机器上也能运行（Windows / 容器均可）。
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from mutagen.mp3 import MP3

from . import db
from .config import CACHE_DIR, MP3_BITRATE, SEGMENT_GAP_SEC
from .textproc import chunk_long_text, parse_segments, to_tts_text
from .tts import synth


def _ffmpeg_bin() -> str:
    """定位 ffmpeg 可执行文件路径。"""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError(
            "未找到 ffmpeg。请安装 ffmpeg 到 PATH，或 pip install imageio-ffmpeg。"
        )


def _mp3_duration(path: Path) -> float:
    """用 mutagen 读取 MP3 时长（秒），纯 Python，无需 ffprobe。"""
    audio = MP3(str(path))
    return float(audio.info.length)


def _make_silence(path: Path, sec: float, ffmpeg: str):
    """生成指定秒数的静音片段（供拼接用）。"""
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{sec}", "-b:a", MP3_BITRATE, str(path)],
        capture_output=True, check=True,
    )


def _concat_mp3s(parts: list[Path], out_path: Path, ffmpeg: str):
    """用 ffmpeg concat demuxer 按顺序拼接 MP3（要求采样率/码率一致）。"""
    concat_list = out_path.parent / (out_path.stem + ".concat.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.as_posix()}'\n")
    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(out_path)],
        capture_output=True, check=True,
    )
    concat_list.unlink(missing_ok=True)


async def generate_file(fid: int, raw_text: str, rel_path: str) -> None:
    """对一个文件执行完整生成流程。异常时置 failed 并向上抛出。"""
    db.set_status(fid, "generating")
    ffmpeg = _ffmpeg_bin()

    items = parse_segments(raw_text)
    if not items:
        db.set_status(fid, "ready", audio_path=None, duration=0.0)
        return

    # 相对路径结构在缓存目录下镜像，避免同名冲突
    cache_rel = rel_path.rsplit(".", 1)[0] + ".mp3"
    final_mp3 = CACHE_DIR / cache_rel
    final_mp3.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        seg_meta: list[dict] = []   # 每条 {text, dur}
        part_files: list[Path] = []

        for item in items:
            tts_text = to_tts_text(item)
            for ci, chunk in enumerate(chunk_long_text(tts_text)):
                seg_mp3 = tmpdir / f"seg_{len(part_files):04d}.mp3"
                await synth(chunk, str(seg_mp3))
                dur = _mp3_duration(seg_mp3)
                # 同一知识点被切块时，展示文本仅首块带"第N条"前缀，其余为续文
                display_text = tts_text if ci == 0 else chunk
                seg_meta.append({"text": display_text, "dur": dur})
                part_files.append(seg_mp3)

        # 需要条间静音时（>1 段），构造拼接序列：seg0, silence, seg1, ...
        silence_file: Path | None = None
        if len(part_files) > 1 and SEGMENT_GAP_SEC > 0:
            silence_file = tmpdir / "silence.mp3"
            _make_silence(silence_file, SEGMENT_GAP_SEC, ffmpeg)

        concat_parts: list[Path] = []
        for i, pf in enumerate(part_files):
            concat_parts.append(pf)
            if i < len(part_files) - 1 and silence_file is not None:
                concat_parts.append(silence_file)

        if len(concat_parts) == 1:
            shutil.move(str(concat_parts[0]), str(final_mp3))
        else:
            _concat_mp3s(concat_parts, final_mp3, ffmpeg)

        total_duration = _mp3_duration(final_mp3)

        # 依据实际拼接顺序计算每条起止秒
        segs: list[dict] = []
        cursor = 0.0
        gap = SEGMENT_GAP_SEC if silence_file is not None else 0.0
        for i, meta in enumerate(seg_meta):
            start = cursor
            end = cursor + meta["dur"]
            segs.append({"idx": i, "text": meta["text"], "start_sec": start, "end_sec": end})
            cursor = end
            if i < len(seg_meta) - 1:
                cursor += gap

    db.replace_segments(fid, segs)
    db.set_status(fid, "ready", audio_path=cache_rel, duration=total_duration)


async def generate_file_safe(fid: int, raw_text: str, rel_path: str) -> bool:
    """带异常保护的生成入口，返回是否成功。"""
    try:
        await generate_file(fid, raw_text, rel_path)
        return True
    except Exception:
        db.set_status(fid, "failed")
        return False
