"""외부 API 만 가짜로 바꾸고 ffmpeg 는 실제로 돌리는 종단 간 테스트.

시나리오 (5 장면):
  1 loop_video 성공 / 2 image → Switch1 에서 제외 / 3 loop_video 실패(nsfw) → 장면 제외
  4·5 loop_video 성공
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from shorts_pipeline import ReportInput, Settings, ShortsPipeline
from shorts_pipeline.errors import AssetGenerationError, PipelineError
from shorts_pipeline.higgsfield import Asset
from shorts_pipeline.tts import TTSResult

from .conftest import requires_ffmpeg


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def probe(path, entries="format=duration"):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)


SCENES = [
    {"scene_number": i, "duration": 3, "narration": n, "caption": f"캡션{i}", "visual_direction": f"연출{i}"}
    for i, n in enumerate([
        "AI 투자가 늘면서 HBM 수요도 빠르게 증가합니다.",
        "SK hynix가 최대 수혜를 받고 있죠!",
        "유가는 120달러를 넘었습니다.",
        "반도체 정유주 전략은 무엇일까요?",
        "보고서 전문에서 확인하세요.",
    ], start=1)
]
ASSET_PLAN = {1: "loop_video", 2: "image", 3: "loop_video", 4: "loop_video", 5: "loop_video"}


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def structured(self, prompt, key):
        self.prompts.append((key, prompt))
        if key == "summarize":
            assert "테스트 보고서 본문" in prompt
            return {"report_title": "테스트", "one_line_summary": "요약", "key_points": ["a"],
                    "important_facts": ["b"], "shorts_angle": "c"}
        if key == "script":
            assert '"report_title":"테스트"' in prompt
            return {"video_title": "AI 랠리, 한국 수혜주는?", "hook": "h", "estimated_duration": 15,
                    "full_script": " ".join(s["narration"] for s in SCENES), "scenes": [dict(s) for s in SCENES]}
        assert '"narration":"보고서 전문에서 확인하세요."' in prompt  # 전체 장면 목록 삽입
        n = int(re.search(r"scene_number: (\d+)", prompt).group(1))
        dur = float(re.search(r"duration: ([\d.]+)", prompt).group(1))
        sc = SCENES[n - 1]
        return {**sc, "duration": dur, "recommended_asset": ASSET_PLAN[n],
                "image_prompt": f"image {n}", "loop_video_prompt": f"video {n}"}


class FakeTTS:
    """글자 수에 비례한 길이의 사인파 wav + 균등 분배한 단어 타임스탬프"""

    def __init__(self, tmp):
        self.tmp = tmp
        self.i = 0

    def synthesize(self, text):
        self.i += 1
        words = text.split()
        dur = round(0.35 * len(words) + 0.4, 3)
        path = self.tmp / f"tts_{self.i}.wav"
        ff("-f", "lavfi", "-i", f"sine=frequency={300 + 40 * self.i}:duration={dur}", "-ar", "44100", str(path))
        step = (dur - 0.2) / len(words)
        ts = [{"text": w, "start": round(0.1 + k * step, 3), "end": round(0.1 + (k + 1) * step - 0.02, 3)}
              for k, w in enumerate(words)]
        return TTSResult(audio=path.read_bytes(), audio_format="wav", audio_duration=dur, words=ts)


class FakeAssets:
    def __init__(self, tmp):
        self.tmp = tmp
        self.calls = []

    def generate(self, visual):
        n = visual["scene_number"]
        self.calls.append((n, visual["recommended_asset"], visual["duration"]))
        if n == 3:
            raise AssetGenerationError("higgsfield", "video 생성 실패 (status=nsfw)", scene=n)
        path = self.tmp / f"v{n}.mp4"
        # 실제 Higgsfield 출력처럼 1080x1920, 24fps, 길이는 음성보다 짧게(패딩 검증)
        ff("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=24:duration=1.5", "-pix_fmt", "yuv420p", str(path))
        return Asset("video", path.read_bytes())


class FakeYouTube:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def upload(self, path, title):
        assert path.is_file()
        self.calls.append((path, title))
        if self.error:
            raise self.error
        return "VID123"


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.output_dir = tmp_path / "out"
    s.fonts_dir = Path(os.environ.get("TEST_FONTS_DIR", tmp_path / "nofonts"))
    return s


@requires_ffmpeg
@pytest.mark.parametrize("keep_temp", [False, True])
def test_full_pipeline_with_real_ffmpeg(tmp_path, settings, keep_temp):
    settings.keep_temp = keep_temp
    llm, tts, assets, yt = FakeLLM(), FakeTTS(tmp_path), FakeAssets(tmp_path), FakeYouTube()
    pipe = ShortsPipeline(settings, llm=llm, tts=tts, assets=assets, youtube=yt)
    report = ReportInput.from_dict({"title": "t", "text": "테스트 보고서 본문입니다."})
    res = pipe.run(report, run_name=f"case_keep{keep_temp}")

    # --- 결과 메타 ---
    assert res.scenes_used == [1, 4, 5] and sorted(res.scenes_skipped) == [2, 3]
    assert re.fullmatch(r"\d{8}_AI_랠리_한국_수혜주는\.mp4", res.video_path.name)
    assert res.video_path.parent == settings.output_dir.resolve()
    assert [c[1] for c in yt.calls] == [res.video_path.stem.replace("_", " ")] and res.youtube_video_id == "VID123"
    assert json.loads((res.run_dir / "result.json").read_text(encoding="utf-8"))["youtube_video_id"] == "VID123"

    # --- 호출 순서/값: 시각화 프롬프트에 Typecast 실제 길이가 들어가는지 ---
    keys = [k for k, _ in llm.prompts]
    assert keys == ["summarize", "script", "visual", "visual", "visual", "visual", "visual"]
    tts_meta = json.loads((res.run_dir / "tts.json").read_text(encoding="utf-8"))
    assert [c[0] for c in assets.calls] == [1, 3, 4, 5]  # image 장면은 생성(과금)하지 않음
    durations = {m["scene_number"]: m["audio_duration"] for m in tts_meta}
    for n, kind, dur in assets.calls:
        assert dur == durations[n]

    # --- 최종 영상: 720x1280, 오디오 존재, 길이 = Σ(사용된 장면 음성 길이)/1.5 ---
    info = probe(res.video_path, "stream=codec_type,width,height:format=duration")
    v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (720, 1280)
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    expected = sum(m["actual_duration"] for m in tts_meta if m["scene_number"] in res.scenes_used) / 1.5
    assert float(info["format"]["duration"]) == pytest.approx(expected, abs=0.25)
    assert res.subtitle_count > 0

    work = res.run_dir / "work"
    for name in ("summary.json", "script.json", "tts.json", "visuals.json", "result.json", "run.log"):
        assert (res.run_dir / name).is_file(), name
    log_text = (res.run_dir / "run.log").read_text(encoding="utf-8")
    for text in ("scene 2 건너뜀", "scene 3 건너뜀", "✔ 8. 자막 입히기", "✔ 9. YouTube 업로드"):
        assert text in log_text

    if keep_temp:
        srt = (work / "subtitles.srt").read_text(encoding="utf-8")
        assert srt.startswith("1\n00:00:00,")
        # 장면별 최종 길이가 오디오 길이에 맞춰졌는지 (tpad/trim)
        for n in res.scenes_used:
            d = float(probe(work / f"scene_{n}_final.mp4")["format"]["duration"])
            a = next(m["actual_duration"] for m in tts_meta if m["scene_number"] == n)
            assert d == pytest.approx(a, abs=0.06)
        assert not (work / "scene_3.mp4").exists() and not (work / "scene_2.mp4").exists()
        concat = (work / "concat_final.txt").read_text(encoding="utf-8").splitlines()
        assert concat == [f"file 'scene_{n}_final.mp4'" for n in res.scenes_used]
    else:
        leftovers = [p.name for p in work.iterdir()]
        assert leftovers == [], leftovers


@requires_ffmpeg
def test_all_scenes_failing_raises(tmp_path, settings):
    class Fail(FakeAssets):
        def generate(self, visual):
            raise AssetGenerationError("higgsfield", "x", scene=visual["scene_number"])

    yt = FakeYouTube()
    pipe = ShortsPipeline(settings, llm=FakeLLM(), tts=FakeTTS(tmp_path), assets=Fail(tmp_path), youtube=yt)
    with pytest.raises(PipelineError, match="생성된 장면이 하나도 없습니다"):
        pipe.run("테스트 보고서 본문", run_name="fail")
    err = json.loads((settings.output_dir / "runs" / "fail" / "error.json").read_text(encoding="utf-8"))
    assert err["step"] == "assets" and yt.calls == []


@requires_ffmpeg
def test_upload_failure_keeps_video_and_temp(tmp_path, settings):
    yt = FakeYouTube(error=PipelineError("youtube", "업로드 실패"))
    pipe = ShortsPipeline(settings, llm=FakeLLM(), tts=FakeTTS(tmp_path), assets=FakeAssets(tmp_path), youtube=yt)
    with pytest.raises(PipelineError, match="업로드 실패"):
        pipe.run("테스트 보고서 본문", run_name="upfail")
    run_dir = settings.output_dir / "runs" / "upfail"
    assert json.loads((run_dir / "error.json").read_text(encoding="utf-8"))["step"] == "youtube"
    assert yt.calls[0][0].is_file() and (run_dir / "work" / "subtitles.srt").is_file()  # n8n: 정리 단계 전에 멈춤


@requires_ffmpeg
def test_no_upload_mode(tmp_path, settings):
    settings.youtube_upload = False
    pipe = ShortsPipeline(settings, llm=FakeLLM(), tts=FakeTTS(tmp_path), assets=FakeAssets(tmp_path))
    res = pipe.run("테스트 보고서 본문", run_name="noup")
    assert res.video_path.is_file() and res.youtube_video_id is None


CORE_KEYS = ("OPENAI_API_KEY", "TYPECAST_API_KEY", "HIGGSFIELD_API_KEY", "HIGGSFIELD_API_SECRET")
YT_KEYS = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")


def test_missing_credentials_message(monkeypatch, tmp_path):
    for k in (*CORE_KEYS, *YT_KEYS, "YOUTUBE_UPLOAD"):
        monkeypatch.delenv(k, raising=False)
    from shorts_pipeline.config import ConfigError
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        ShortsPipeline(Settings.from_env(tmp_path / "none.env"))


def test_missing_youtube_credentials_fail_before_any_work(monkeypatch, tmp_path):
    from shorts_pipeline.config import ConfigError
    for k in CORE_KEYS:
        monkeypatch.setenv(k, "x")
    for k in (*YT_KEYS, "YOUTUBE_UPLOAD"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(tmp_path / "none.env")
    with pytest.raises(ConfigError, match="YOUTUBE_REFRESH_TOKEN.*--no-upload"):
        s.require_credentials()
    s.youtube_upload = False
    s.require_credentials()
