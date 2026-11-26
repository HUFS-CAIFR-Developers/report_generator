"""`Create SRT from Typecast` Code 노드(JavaScript)를 1:1 로 옮긴 것.

반올림은 JS Math.round(반올림 시 +∞ 방향) 와 맞추려고 floor(x + 0.5) 를 쓴다.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .media import js_num

MAX_CHARS = 13
MAX_GAP = 0.38
_SENTENCE_END = re.compile(r"[.!?。！？]$")
_WS = re.compile(r"\s")


class SubtitleError(ValueError):
    pass


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def to_srt_time(seconds: float) -> str:
    ms = max(0, math.floor(seconds * 1000 + 0.5))
    h = ms // 3600000
    m = (ms % 3600000) // 60000
    s = (ms % 60000) // 1000
    milli = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def make_chunks(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush(ws):
        chunks.append({"text": " ".join(w["text"] for w in ws), "start": ws[0]["start"], "end": ws[-1]["end"]})

    for word in words:
        if (not word or not isinstance(word.get("text"), str)
                or not _is_num(word.get("start")) or not _is_num(word.get("end"))):
            continue
        if not current:
            current.append(word)
            continue
        prev = current[-1]
        candidate_text = " ".join(w["text"] for w in [*current, word])
        candidate_len = len(_WS.sub("", candidate_text))
        gap = word["start"] - prev["end"]
        prev_ends_sentence = bool(_SENTENCE_END.search(prev["text"]))
        if candidate_len > MAX_CHARS or gap > MAX_GAP or prev_ends_sentence:
            flush(current)
            current = [word]
        else:
            current.append(word)
    if current:
        flush(current)
    return chunks


def build_srt(items: list[dict[str, Any]]) -> dict[str, Any]:
    """items: [{scene_number, words, final_scene_duration}, ...] → {srt, subtitle_count, total_duration}"""
    items = sorted(items, key=lambda it: float(it["scene_number"]))
    srt = ""
    index = 1
    offset = 0.0
    for it in items:
        scene = it["scene_number"]
        words = it.get("words") or []
        try:
            scene_duration = float(it.get("final_scene_duration"))
        except (TypeError, ValueError):
            scene_duration = float("nan")
        if not isinstance(words, list) or len(words) == 0:
            raise SubtitleError(f"Typecast words missing for scene {scene}")
        if not math.isfinite(scene_duration) or scene_duration <= 0:
            raise SubtitleError(f"Final scene duration missing for scene {scene}")
        try:
            last_end = float(words[-1].get("end"))
        except (TypeError, ValueError):
            last_end = float("nan")
        if math.isfinite(last_end) and last_end > scene_duration + 0.25:
            raise SubtitleError(
                f"Scene {scene}: speech timestamp exceeds final scene duration. "
                f"last word={js_num(last_end)}, scene={js_num(scene_duration)}")
        for chunk in make_chunks(words):
            start = offset + chunk["start"]
            end = offset + min(chunk["end"], scene_duration)
            srt += f"{index}\n{to_srt_time(start)} --> {to_srt_time(end)}\n{chunk['text']}\n\n"
            index += 1
        offset += scene_duration
    return {"srt": srt, "subtitle_count": index - 1, "total_duration": offset}
