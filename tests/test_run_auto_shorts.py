"""run_auto._run_shorts 연결 확인: 숏츠 결과에 따라 리포트를 다시 올리는지, 실패해도 예외 없이 끝나는지.
외부 API는 부르지 않는다. 실행: python -m pytest tests/test_run_auto_shorts.py"""
import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENDART_API_KEY", "test")

import shorts_pipeline  # noqa: E402

import run_auto  # noqa: E402

TODAY = datetime(2026, 11, 26, 9, 0)
PDF = Path("/tmp/report.pdf")


def _setup(monkeypatch, make_shorts):
    calls = {"post": [], "alerts": []}
    monkeypatch.setenv("TYPECAST_API_KEY", "tc")
    monkeypatch.setattr(shorts_pipeline, "make_shorts", make_shorts)
    monkeypatch.setattr(run_auto, "post_report", lambda *a, **k: calls["post"].append((a, k)))
    monkeypatch.setattr(run_auto, "send_text_private", lambda msg: calls["alerts"].append(msg))
    monkeypatch.setitem(run_auto.RUN_STATE, "context", {"final_title": "t"})
    return calls


def test_skipped_without_keys(monkeypatch):
    calls = _setup(monkeypatch, lambda *a: 1 / 0)
    monkeypatch.delenv("TYPECAST_API_KEY")
    assert run_auto._run_shorts(TODAY, PDF) == "skipped"
    assert calls["post"] == [] and calls["alerts"] == []


def test_uploaded_links_url_without_card(monkeypatch):
    seen = {}

    def fake(pdf, settings):
        seen["pdf"], seen["settings"] = pdf, settings
        return SimpleNamespace(youtube_video_id="abc123", video_path=Path("/tmp/v.mp4"))

    calls = _setup(monkeypatch, fake)
    assert run_auto._run_shorts(TODAY, PDF) == "uploaded"
    (args, kwargs), = calls["post"]
    assert args == (PDF, None, {"final_title": "t"})
    assert kwargs == {"youtube_url": "https://youtube.com/shorts/abc123"}
    assert seen["pdf"] == PDF
    assert seen["settings"].fonts_dir.joinpath("Pretendard-Bold.otf").is_file()
    assert seen["settings"].output_dir.name == "shorts"
    # 서버에서 정하지 않았으면 비공개, 장면당 대기 10분
    assert seen["settings"].youtube_privacy_status == "private"
    assert seen["settings"].poll_timeout_sec == 600


def test_server_settings_win(monkeypatch):
    seen = {}

    def fake(pdf, settings):
        seen["settings"] = settings
        return SimpleNamespace(youtube_video_id=None, video_path=Path("/tmp/v.mp4"))

    _setup(monkeypatch, fake)
    monkeypatch.setenv("YOUTUBE_PRIVACY_STATUS", "public")
    monkeypatch.setenv("POLL_TIMEOUT_SEC", "1200")
    run_auto._run_shorts(TODAY, PDF)
    assert seen["settings"].youtube_privacy_status == "public"
    assert seen["settings"].poll_timeout_sec == 1200


def test_bad_setting_alerts_instead_of_crashing(monkeypatch):
    calls = _setup(monkeypatch, lambda *a: 1 / 0)
    monkeypatch.setenv("SPEED_FACTOR", "abc")
    assert run_auto._run_shorts(TODAY, PDF) == "failed"
    assert "설정 오류" in calls["alerts"][0]


def test_reupload_keeps_report_date(monkeypatch, tmp_path):
    from report import api_upload

    sent = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"id": "r1"}

    def fake_post(url, files, **kwargs):
        sent["report"] = json.loads(files["report"][1])
        return Resp()

    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(api_upload.config, "REPORT_API_TOKEN", "t")
    monkeypatch.setattr(api_upload.config, "REPORT_API_URL", "https://api.example.com/api/generator/reports")
    monkeypatch.setattr(api_upload.requests, "post", fake_post)
    context = {"date": "2026.11.26", "company1": "삼성전자", "final_title": "t", "final_summary": "s",
               "article_summary1": "k", "article_title": "a", "article_content": "c"}
    api_upload.post_report(pdf, None, context, youtube_url="https://youtube.com/shorts/abc")
    # 자정이 지나 다시 올려도 리포트를 만든 날짜 그대로
    assert sent["report"]["date"] == "2026-11-26"
    assert sent["report"]["youtube_url"] == "https://youtube.com/shorts/abc"


def test_no_upload_does_not_repost(monkeypatch):
    calls = _setup(monkeypatch, lambda *a: SimpleNamespace(youtube_video_id=None, video_path=Path("/tmp/v.mp4")))
    assert run_auto._run_shorts(TODAY, PDF) == "no_upload"
    assert calls["post"] == []


def test_failure_alerts_and_returns(monkeypatch):
    def boom(*a):
        raise shorts_pipeline.PipelineError("tts", "크레딧 없음")

    calls = _setup(monkeypatch, boom)
    assert run_auto._run_shorts(TODAY, PDF) == "failed"
    assert calls["post"] == [] and "숏츠 실패" in calls["alerts"][0]


def test_link_failure_alerts_with_url(monkeypatch):
    calls = _setup(monkeypatch, lambda *a: SimpleNamespace(youtube_video_id="abc123", video_path=Path("/tmp/v.mp4")))

    def fail(*a, **k):
        raise RuntimeError("HTTP 500")

    monkeypatch.setattr(run_auto, "post_report", fail)
    assert run_auto._run_shorts(TODAY, PDF) == "link_failed"
    assert "https://youtube.com/shorts/abc123" in calls["alerts"][0]
