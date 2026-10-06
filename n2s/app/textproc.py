"""文本预处理：分条、编号转写、Markdown 清洗。

规则（见实施蓝图 3.3）：
1. 按行解析，`数字.`/`数字、`/`数字)`/`数字．` 开头为新条；
   不带编号的行并入上一条（作为补充说明）；
   首行无编号则自成一条。
2. 编号可转写为中文序数（"第一条""第二条"），由 config.READ_NUMBER_AS_ORDINAL 控制。
3. 去掉 ** 、* 、` 、# 、链接 []() 等 Markdown 标记；代码块/表格整块跳过。
"""
import re

from .config import READ_NUMBER_AS_ORDINAL, MAX_SEGMENT_CHARS

# 编号行匹配：行首（可含空格）数字 + 分隔符
_NUM_HEAD = re.compile(r"^\s*(\d+)\s*[.、)．]\s*(.*)$")

_CN_DIGITS = "零一二三四五六七八九"


def _num_to_cn(n: int) -> str:
    if n == 0:
        return "零"
    parts = []
    while n > 0:
        parts.append(_CN_DIGITS[n % 10])
        n //= 10
    return "".join(reversed(parts))


def _ordinal(n: int) -> str:
    """数字 → 中文序数词：1→第一条, 12→第十二条"""
    return "第" + _num_to_cn(n) + "条"


def _clean_inline(text: str) -> str:
    """清洗单行内的 Markdown 标记。"""
    t = text
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)   # [文字](链接) → 文字
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)        # 图片整删
    t = t.replace("**", "").replace("__", "")
    t = t.replace("`", "")
    t = re.sub(r"^#{1,6}\s*", "", t)                  # 标题 # 号
    t = re.sub(r"^\s*>\s?", "", t)                    # 引用
    t = re.sub(r"^\s*[-*+]\s+", "", t)                # 无序列表
    t = t.strip()
    return t


def parse_segments(raw_text: str) -> list[dict]:
    """将原始文本解析为朗读条目列表。

    返回：[{'text': str, 'number': int|None}]
    number 为该条的原始编号（用于转写序数），无编号为 None。
    """
    lines = raw_text.splitlines()
    items: list[dict] = []          # 最终条目
    in_code_block = False
    in_table = False

    for line in lines:
        stripped = line.strip()

        # 代码块开关
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # 表格行跳过（含 | 且非编号行）
        if stripped.startswith("|") or (in_table and "|" in stripped):
            in_table = "|" in stripped
            continue

        if not stripped:
            continue

        m = _NUM_HEAD.match(line)
        if m:
            num = int(m.group(1))
            body = _clean_inline(m.group(2))
            if body:
                items.append({"text": body, "number": num})
            continue

        # 无编号行：并入上一条
        cleaned = _clean_inline(stripped)
        if not cleaned:
            continue
        if items:
            items[-1]["text"] += "。" + cleaned
        else:
            items.append({"text": cleaned, "number": None})

    return items


def to_tts_text(item: dict) -> str:
    """将一条目转成实际送 TTS 的文本（应用编号转写）。"""
    if READ_NUMBER_AS_ORDINAL and item["number"] is not None:
        prefix = _ordinal(item["number"]) + "。"
        return prefix + item["text"]
    return item["text"]


def chunk_long_text(text: str, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """超长单条按标点切块，避免 edge-tts 单次请求过长。"""
    if len(text) <= max_chars:
        return [text]
    # 按句末标点切分，贪心累积
    sentences = re.split(r"(?<=[。！？；!?;])", text)
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) > max_chars and cur:
            chunks.append(cur)
            cur = s
        else:
            cur += s
    if cur:
        chunks.append(cur)
    return chunks
