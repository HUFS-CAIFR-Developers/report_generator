"""보고서 → 쇼츠 영상 오케스트레이션 (n8n `보고서 기반 쇼츠 자동화` 전체 흐름).

  1 보고서 요약정리 (OpenAI)            6 장면 영상 정규화 (ffmpeg)
  2 쇼츠 대본 생성 (OpenAI)             7 장면별 오디오 길이 맞춤 + 합성, 이어붙이기
  3 장면별 TTS + 타임스탬프 (Typecast)  8 SRT 생성 (최종 장면 길이 기준)
  4 장면별 시각화 프롬프트 (OpenAI)     9 자막 입히기 → 1.5배속 → 파일명 지정
  5 장면별 영상 생성 (Higgsfield, 실패 장면은 제외)       10 YouTube 업로드 → 임시파일 정리
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import llm as llm_mod
from .config import Settings
from .errors import AssetGenerationError, PipelineError
from .higgsfield import AssetClient, HiggsfieldClient
from .interface import ReportInput
from .logging_setup import get_logger, setup_logging, step
from .media import FFmpeg, cleanup, final_scene_files
from .subtitles import SubtitleError, build_srt
from .tts import TTSClient, TypecastClient, save_audio
from .youtube import YouTubeClient, YouTubeUploader, youtube_title

log = get_logger("pipeline")


@dataclass
class VideoResult:
    video_path: Path
    video_title: str
    run_dir: Path
    scenes_total: int
    scenes_used: list[int]
    scenes_skipped: dict[int, str] = field(default_factory=dict)
    final_duration: float | None = None
    subtitle_count: int = 0
    youtube_video_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["video_path"] = str(self.video_path)
        d["run_dir"] = str(self.run_dir)
        return d


def resolve_title(script: dict[str, Any], summary: dict[str, Any]) -> str:
    """Final Filename 노드: video_title || scenes[0].caption || report_title || 'shorts'"""
    scenes = script.get("scenes") or [{}]
    return script.get("video_title") or scenes[0].get("caption") or summary.get("report_title") or "shorts"


def final_filename(title: str, now: datetime) -> str:
    """Final Filename 노드: yyyyMMdd_ + 특수문자 제거/공백→_ 제목 + .mp4"""
    t = re.sub(r"[^0-9A-Za-z가-힣 _-]", "", str(title)).strip()
    t = re.sub(r"\s+", "_", t)
    return f"{now.strftime('%Y%m%d')}_{t}.mp4"


def _now(tz_name: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:  # tzdata 미설치 등
        log.warning("타임존 %s 를 불러오지 못해 로컬 시간을 사용합니다", tz_name)
        return datetime.now()


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class ShortsPipeline:
    def __init__(self, settings: Settings, *, llm: llm_mod.LLMClient | None = None,
                 tts: TTSClient | None = None, assets: AssetClient | None = None,
                 youtube: YouTubeClient | None = None):
        self.s = settings
        if llm is None or tts is None or assets is None or (settings.youtube_upload and youtube is None):
            settings.require_credentials()
        self.llm = llm or llm_mod.OpenAIClient(settings.openai_api_key, settings.openai_model)
        self.tts = tts or TypecastClient(settings.typecast_api_key, settings.typecast_voice_id, settings.typecast_model)
        self.assets = assets or HiggsfieldClient(
            settings.higgsfield_auth_header, settings.higgsfield_base_url,
            poll_interval=settings.poll_interval_sec, poll_timeout=settings.poll_timeout_sec)
        self.youtube = youtube
        if settings.youtube_upload and youtube is None:
            self.youtube = YouTubeUploader(
                settings.youtube_client_id, settings.youtube_client_secret, settings.youtube_refresh_token,
                category_id=settings.youtube_category_id, privacy_status=settings.youtube_privacy_status)

    # ------------------------------------------------------------------
    def run(self, report: Any, run_name: str | None = None) -> VideoResult:
        report = ReportInput.from_any(report)
        started = _now(self.s.timezone)
        run_dir = (self.s.output_dir / "runs" / (run_name or started.strftime("%Y%m%d_%H%M%S"))).resolve()
        work = run_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        setup_logging(run_dir / "run.log")
        log.info("실행 시작: source=%s, 본문 %d자, run_dir=%s", report.source, len(report.text), run_dir)

        ff = FFmpeg(work, self.s.ffmpeg_bin, self.s.ffprobe_bin)
        ff.check_available()

        try:
            return self._run(report, run_dir, work, ff)
        except Exception as e:
            _dump(run_dir / "error.json", {"error": str(e), "type": type(e).__name__,
                                           "step": getattr(e, "step", None), "scene": getattr(e, "scene", None)})
            log.error("실행 실패: %s (임시파일은 %s 에 남겨둠)", e, work)
            raise

    # ------------------------------------------------------------------
    def _run(self, report: ReportInput, run_dir: Path, work: Path, ff: FFmpeg) -> VideoResult:
        with step("1. 보고서 내용 요약정리"):
            summary = llm_mod.summarize_report(self.llm, report.text)
            _dump(run_dir / "summary.json", summary)

        with step("2. AI 쇼츠대본 생성"):
            script = llm_mod.generate_script(self.llm, summary)
            _dump(run_dir / "script.json", script)
        scenes: list[dict[str, Any]] = script["scenes"]

        # 3. Split Out → Typecast TTS → 파일 저장 → ffprobe (Merge6/8, Edit Fields3, sort_audio_duration)
        audio: dict[int, dict[str, Any]] = {}
        with step(f"3. 장면별 TTS ({len(scenes)}개)"):
            for sc in scenes:
                n = int(sc["scene_number"])
                if n in audio:
                    raise PipelineError("tts", "scene_number 가 중복됩니다", scene=n)
                try:
                    res = self.tts.synthesize(sc["narration"])
                except PipelineError as e:
                    raise PipelineError("tts", str(e), scene=n) from e
                save_audio(res, work, n)
                actual = ff.probe_duration(f"audio_{n}.wav")
                audio[n] = {"scene_number": n, "actual_duration": actual, "words": res.words,
                            "audio_duration": res.audio_duration if res.audio_duration is not None else actual}
                log.info("scene %d: 음성 %.2fs, 단어 %d개", n, actual, len(res.words))
            _dump(run_dir / "tts.json", sorted(audio.values(), key=lambda a: a["scene_number"]))

        # 4. Merge Scene + Typecast → 시각화 자료 프롬포트
        visuals: list[dict[str, Any]] = []
        with step("4. 장면별 시각화 프롬프트"):
            for sc in scenes:
                n = int(sc["scene_number"])
                v = llm_mod.generate_visual_prompt(self.llm, sc, audio[n]["audio_duration"], scenes)
                v["scene_number"] = n  # Normalize Scene Data
                visuals.append(v)
                log.info("scene %d: %s", n, v["recommended_asset"])
            _dump(run_dir / "visuals.json", visuals)

        # 5~6. Loop Over Items(순차) → Higgsfield → Sort → Merge_duration_into_visual → Switch1 → ffmpeg
        skipped: dict[int, str] = {}
        with step("5. 장면별 영상 생성 및 렌더링"):
            for v in sorted(visuals, key=lambda x: x["scene_number"]):
                n = v["scene_number"]
                if v["recommended_asset"] != "loop_video":
                    # n8n: Switch1 이 loop_video 만 통과시켜 image 장면은 생성만 되고 영상에서 빠짐
                    # → 결과가 같으므로 버려질 이미지를 생성(과금)하지 않고 바로 건너뜀
                    skipped[n] = "recommended_asset=image (Switch1 에 image 출력 없음)"
                    log.warning("scene %d 건너뜀: recommended_asset=image 는 최종 영상에 포함되지 않습니다", n)
                    continue
                try:
                    asset = self.assets.generate(v)
                except AssetGenerationError as e:
                    # n8n: 실패 상태는 HF Video Status Switch 출력이 없어 장면이 빠진 채 진행됨 → 동일하게 건너뜀
                    skipped[n] = str(e)
                    log.error("scene %d 건너뜀: %s", n, e)
                    continue
                # Read/Write Files from Disk1 → Execute Command1
                (work / f"scene_{n}_raw.mp4").write_bytes(asset.data)
                ff.normalize_video(n)
                log.info("scene %d: %s 정규화 완료", n, asset.asset_type)
        used = sorted(set(audio) - set(skipped))
        if not used:
            raise PipelineError("assets", "생성된 장면이 하나도 없습니다")

        # 7. Execute Command2: 장면별 오디오 길이 맞춤 + 합성 → concat
        with step("6. 장면 합성 및 이어붙이기"):
            for n in used:
                ff.finalize_scene(n)
            finals = final_scene_files(work)
            ff.concat(finals)

        # 8. Measure/Parse Final Scene Durations → Merge SRT Timing → Create SRT
        with step("7. 자막(SRT) 생성"):
            items = []
            for name in finals:
                n = int(name[len("scene_"):-len("_final.mp4")])
                if n in audio:
                    items.append({**audio[n], "final_scene_duration": ff.probe_duration(name)})
            try:
                srt = build_srt(items)
            except SubtitleError as e:
                raise PipelineError("subtitles", str(e)) from e
            (work / "subtitles.srt").write_text(srt["srt"], encoding="utf-8")
            log.info("자막 %d개, 총 %.2fs", srt["subtitle_count"], srt["total_duration"])

        with step("8. 자막 입히기 · 배속 · 파일명 지정"):
            self._prepare_fonts(work)
            ff.burn_subtitles()
            ff.speed_up(self.s.speed_factor)
            title = resolve_title(script, summary)
            name = final_filename(title, _now(self.s.timezone))
            self.s.output_dir.mkdir(parents=True, exist_ok=True)
            dest = (self.s.output_dir / name).resolve()
            shutil.move(str(work / "final_speed.mp4"), dest)  # Rename Final Video (덮어쓰기)
            final_duration = FFmpeg(dest.parent, self.s.ffmpeg_bin, self.s.ffprobe_bin).probe_duration(dest.name)

        result = VideoResult(video_path=dest, video_title=title, run_dir=run_dir,
                             scenes_total=len(scenes), scenes_used=used, scenes_skipped=skipped,
                             final_duration=final_duration,
                             subtitle_count=srt["subtitle_count"])
        _dump(run_dir / "result.json", result.to_dict())

        if self.youtube is not None and self.s.youtube_upload:
            with step("9. YouTube 업로드"):
                result.youtube_video_id = self.youtube.upload(dest, youtube_title(dest.name))
                _dump(run_dir / "result.json", result.to_dict())
        else:
            log.info("YouTube 업로드 건너뜀 (--no-upload)")

        if self.s.keep_temp:
            log.info("KEEP_TEMP=true → 임시파일 유지: %s", work)
        else:
            with step("10. 임시파일 정리"):
                cleanup(work)
        log.info("완료: %s (%.1fs, 장면 %d/%d, 제외 %s)", dest, final_duration, len(used), len(scenes),
                 sorted(skipped) or "없음")
        return result

    def _prepare_fonts(self, work: Path) -> None:
        src = Path(self.s.fonts_dir)
        dst = work / "fonts"
        dst.mkdir(exist_ok=True)
        fonts = [p for p in src.glob("*") if p.suffix.lower() in (".otf", ".ttf", ".ttc")] if src.is_dir() else []
        if not fonts:
            log.warning("FONTS_DIR(%s)에 폰트가 없습니다. Pretendard 대신 시스템 기본 폰트로 자막이 렌더링됩니다", src)
        for f in fonts:
            shutil.copy2(f, dst / f.name)


def make_shorts(report: Any, settings: Settings | None = None, **clients: Any) -> VideoResult:
    """보고서 생성 코드에서 부르는 단일 진입점.

        from shorts_pipeline import make_shorts
        result = make_shorts(report_text_or_path_or_dict)
        print(result.video_path)
    """
    return ShortsPipeline(settings or Settings.from_env(), **clients).run(report)
