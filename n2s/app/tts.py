"""edge-tts 封装：单条文本转 MP3。串行队列 + 退避重试由 pipeline 层控制。"""
import asyncio

import edge_tts

from .config import TTS_VOICE, TTS_RATE

MAX_RETRY = 3
RETRY_BASE_DELAY = 2.0  # 秒，指数退避基数


async def _synth_once(text: str, out_path: str):
    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
    await communicate.save(out_path)


async def synth(text: str, out_path: str) -> None:
    """生成单条音频，带指数退避重试（应对限流 429 / 网络抖动）。"""
    last_err = None
    for attempt in range(MAX_RETRY):
        try:
            await _synth_once(text, out_path)
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < MAX_RETRY - 1:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
    raise RuntimeError(f"edge-tts 生成失败（重试 {MAX_RETRY} 次）: {last_err}")
