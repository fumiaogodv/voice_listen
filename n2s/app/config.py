"""全局配置。所有可调参数集中在此。"""
import os
from pathlib import Path

# 项目根目录（本文件在 app/ 下，根即上一级）
BASE_DIR = Path(__file__).resolve().parent.parent

# 数据目录
NOTES_DIR = Path(os.getenv("NOTES_DIR", BASE_DIR / "data" / "notes"))
CACHE_DIR = Path(os.getenv("CACHE_DIR", BASE_DIR / "data" / "audio_cache"))
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "n2s.db"))

# TTS
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")   # 默认女声，可改 zh-CN-YunxiNeural（男声）
TTS_RATE = os.getenv("TTS_RATE", "+0%")                        # 语速微调，如 "+10%"
TTS_CONCURRENCY = 1                                            # 串行生成，防限流

# 编号读法：True = "第一条/第二条"，False = 原样保留编号
READ_NUMBER_AS_ORDINAL = os.getenv("READ_NUMBER_AS_ORDINAL", "1") == "1"

# 条间静音时长（秒）
SEGMENT_GAP_SEC = 0.6

# 输出音频码率
MP3_BITRATE = "64k"

# 扫描间隔（秒）
SCAN_INTERVAL_SEC = 30

# 单条文本长度上限（字符），超过则在本条内再切分（防 edge-tts 单次请求过长）
MAX_SEGMENT_CHARS = 800
