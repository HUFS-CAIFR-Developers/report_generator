"""n8n Execute Command(ffmpeg/ffprobe) 노드 대체.

필터 문자열은 n8n 원본 명령과 글자 하나까지 같게 유지한다 (tests/test_parity_n8n.py 가 검증).
쉘 대신 인자 리스트로 실행하고, 모든 명령은 작업 폴더(cwd)에서 상대 파일명으로 돌린다.
→ Windows 경로(C:\\...)의 콜론/역슬래시가 subtitles 필터를 깨뜨리는 문제를 피한다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .errors import PipelineError
from .logging_setup import get_logger

log = get_logger("media")

SUBTITLE_STYLE = "FontName=Pretendard,Bold=1,FontSize=10.5,Alignment=2,MarginV=105,Outline=1,Shadow=0"


def js_num(x: float | int | str) -> str:
    """n8n `{{ number }}` 출력과 같은 문자열 (4.0 → "4", 4.25 → "4.25")."""
    if isinstance(x, str):
        return x
    f = float(x)
    return str(int(f)) if f.is_integer() else repr(f)


# ---------- 필터 문자열 (n8n 원본과 동일) ----------
VIDEO_NORMALIZE_FILTER = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,fps=30,format=yuv420p"


def scene_final_filter(adur: str) -> str:
    return (f"[0:v]tpad=stop_mode=clone:stop_duration=120,trim=duration={adur},setpts=PTS-STARTPTS,fps=30[v];"
            f"[1:a]atrim=duration={adur},asetpts=PTS-STARTPTS[a]")


def subtitles_filter(srt_name: str = "subtitles.srt", fonts_dir: str = "fonts") -> str:
    return f"subtitles='{srt_name}':fontsdir='{fonts_dir}':force_style='{SUBTITLE_STYLE}'"


def speed_filter(factor: float) -> str:
    f = js_num(factor)
    return f"[0:v]setpts=PTS/{f}[v];[0:a]atempo={f}[a]"


# ---------- 실행기 ----------
class FFmpeg:
    def __init__(self, work_dir: Path, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.work_dir = Path(work_dir)
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def check_available(self) -> None:
        for b in (self.ffmpeg_bin, self.ffprobe_bin):
            if shutil.which(b) is None and not Path(b).is_file():
                raise PipelineError("ffmpeg", f"'{b}' 를 찾을 수 없습니다. ffmpeg 를 설치하거나 FFMPEG_BIN/FFPROBE_BIN 을 지정하세요")

    def _run(self, args: list[str], step: str) -> subprocess.CompletedProcess:
        log.debug("$ %s", " ".join(args))
        try:
            p = subprocess.run(args, cwd=self.work_dir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        except FileNotFoundError as e:
            raise PipelineError(step, f"실행 파일을 찾을 수 없습니다: {args[0]}") from e
        if p.returncode != 0:
            tail = "\n".join((p.stderr or "").strip().splitlines()[-15:])
            raise PipelineError(step, f"exit {p.returncode}\n{tail}")
        return p

    def ffmpeg(self, *args: str, step: str = "ffmpeg") -> None:
        self._run([self.ffmpeg_bin, "-y", *args], step)

    def probe_duration_raw(self, name: str) -> str:
        """ffprobe stdout 그대로 (n8n 쉘 스크립트의 $adur 와 같은 문자열)."""
        p = self._run([self.ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                       "-of", "default=noprint_wrappers=1:nokey=1", name], "ffprobe")
        out = (p.stdout or "").strip()
        if not out:
            raise PipelineError("ffprobe", f"길이를 측정하지 못했습니다: {name}")
        return out

    def probe_duration(self, name: str) -> float:
        raw = self.probe_duration_raw(name)
        try:
            return float(raw)
        except ValueError as e:
            raise PipelineError("ffprobe", f"잘못된 duration '{raw}': {name}") from e

    # ---- 장면 영상 ----
    def normalize_video(self, n: int) -> str:
        """Execute Command1: scene_N_raw.mp4 → 720x1280/30fps scene_N.mp4"""
        out = f"scene_{n}.mp4"
        self.ffmpeg("-i", f"scene_{n}_raw.mp4", "-vf", VIDEO_NORMALIZE_FILTER, "-an",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", out, step=f"scene{n}:normalize")
        return out

    def finalize_scene(self, n: int) -> str:
        """Execute Command2 루프 본문: 오디오 길이에 맞춰 영상 패딩/트림 + 오디오 합성"""
        audio = f"audio_{n}.wav"
        if not (self.work_dir / audio).is_file():
            raise PipelineError("finalize_scene", f"Missing audio: {audio}", scene=n)
        adur = self.probe_duration_raw(audio)
        log.info("Scene %s audio duration = %s", n, adur)
        out = f"scene_{n}_final.mp4"
        self.ffmpeg("-i", f"scene_{n}.mp4", "-i", audio, "-filter_complex", scene_final_filter(adur),
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out,
                    step=f"scene{n}:finalize")
        return out

    def concat(self, final_scenes: list[str], out: str = "final_with_audio.mp4") -> str:
        if not final_scenes:
            raise PipelineError("concat", "No final scene files found.")
        lst = self.work_dir / "concat_final.txt"
        lst.write_text("".join(f"file '{name}'\n" for name in final_scenes), encoding="utf-8")
        self.ffmpeg("-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", out, step="concat")
        return out

    def burn_subtitles(self, src: str = "final_with_audio.mp4", out: str = "final_with_subtitles.mp4") -> str:
        """Execute Command4"""
        self.ffmpeg("-i", src, "-vf", subtitles_filter(), "-c:a", "copy", out, step="subtitles")
        return out

    def speed_up(self, factor: float, src: str = "final_with_subtitles.mp4", out: str = "final_speed.mp4") -> str:
        """speed up final video"""
        self.ffmpeg("-i", src, "-filter_complex", speed_filter(factor), "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                    out, step="speed_up")
        return out


def natural_key(name: str):
    """sort -V 와 같은 자연 정렬"""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def final_scene_files(work_dir: Path) -> list[str]:
    names = [p.name for p in work_dir.glob("scene_*_final.mp4") if re.fullmatch(r"scene_\d+_final\.mp4", p.name)]
    return sorted(names, key=natural_key)


TEMP_PATTERNS = ("audio_*.wav", "audio_*.mp3", "scene_*.png", "scene_*.mp4", "final_with_audio.mp4",
                 "final_with_subtitles.mp4", "final_speed.mp4", "subtitles.srt", "concat_final.txt")


def cleanup(work_dir: Path) -> int:
    """Cleanup Temporary Files"""
    removed = 0
    for pattern in TEMP_PATTERNS:
        for p in work_dir.glob(pattern):
            p.unlink(missing_ok=True)
            removed += 1
    fonts = work_dir / "fonts"
    if fonts.is_dir():
        shutil.rmtree(fonts, ignore_errors=True)
    return removed
