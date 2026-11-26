"""서버 cron이 개장일 아침 9시(KST)에 실행하는 진입점 (DEPLOYMENT.md).
한국거래소(KRX) 개장일이 아니면(주말·공휴일) 아무것도 하지 않고 종료한다."""
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import exchange_calendars as xcals

import config
from analysis import llm
from main import RUN_STATE, run_auto
from report.api_upload import post_report, post_run
from report.telegram_notify import send_text_private

_NETWORK_WAIT_MAX_SECONDS = 120
_NETWORK_WAIT_INTERVAL_SECONDS = 5

# 전체 파이프라인이 이 시간을 넘기면 어딘가 멈춘 것으로 보고 강제 종료한다.
# (2026-10-02에 OpenAI 호출 하나가 15분 넘게 응답 없이 멈췄던 적 있음 - 개별 호출
# 타임아웃(config.OPENAI_TIMEOUT_SECONDS)과 별개로, 다른 어떤 단계가 멈추든 잡아내는
# 전체 안전장치.)
_PIPELINE_TIMEOUT_SECONDS = 600

# 숏츠는 리포트를 올린 뒤 따로 만든다. 장면 영상 생성(Higgsfield)이 오래 걸려 리포트 시간 제한과 따로 둔다
_SHORTS_TIMEOUT_SECONDS = 3600
# 장면 영상은 하나씩 만들어서, 장면당 기다리는 시간을 줄여 멈춘 장면은 건너뛰고 60분 안에 끝나게 한다 (서버 .env의 POLL_TIMEOUT_SEC가 우선)
_SHORTS_SCENE_TIMEOUT_SECONDS = 600
_SHORTS_FONTS_DIR = Path(__file__).resolve().parent / "report" / "html" / "fonts"


def is_krx_trading_day(date) -> bool:
    calendar = xcals.get_calendar("XKRX")
    return calendar.is_session(date.strftime("%Y-%m-%d"))


def _wait_for_network() -> bool:
    """맥이 pmset으로 막 깨어난 직후에는 와이파이 재연결이 덜 끝나 DNS 조회가 실패할 수
    있다 (2026-09-28에 실제로 이 문제로 자동실행이 통째로 실패한 적 있음). 실제 작업을
    시작하기 전에 인터넷이 붙었는지 확인하고, 안 붙어있으면 최대 2분까지 재시도하며 기다린다."""
    deadline = time.time() + _NETWORK_WAIT_MAX_SECONDS
    while time.time() < deadline:
        try:
            socket.getaddrinfo("news.naver.com", 443)
            return True
        except socket.gaierror:
            time.sleep(_NETWORK_WAIT_INTERVAL_SECONDS)
    return False


def _post_run(status: str, started_at: datetime, step: str | None = None, message: str | None = None,
              shorts: str | None = None):
    """실행 기록 (POST /api/generator/runs). 기록이 실패해도 본 작업(시간초과 때의 강제 종료 포함)은 그대로 진행한다."""
    try:
        # 업로드 여부와 사용량을 한곳에서 한 번에 읽어 기록한다 (시간초과 때는 이 뒤의 변화가 빠질 수 있다)
        uploaded = RUN_STATE["uploaded"]
        usage_stats, usage_items = llm.usage_snapshot()
        post_run(
            "daily_report",
            status,
            started_at,
            step=step,
            message=message,
            stats={**usage_stats, "uploaded": uploaded, **({"shorts": shorts} if shorts else {})},
            usage=usage_items,
        )
    except Exception as e:
        print(f"실행 기록 전송 실패 (건너뜀): {type(e).__name__}: {e}")


def _run_shorts(today: datetime, pdf_path: Path) -> str:
    """올린 리포트 PDF로 숏츠를 만들어 유튜브에 올리고, 숏츠 주소를 붙여 리포트를 다시 올린다.
    숏츠가 실패해도 리포트는 이미 올라가 있으므로 예외를 던지지 않고 비공개 채널로 알린 뒤 결과만 돌려준다.
    결과: skipped(키 없음) / no_upload(유튜브 업로드 꺼짐) / uploaded / link_failed / failed / timeout"""
    date = today.strftime("%Y-%m-%d")
    try:
        from shorts_pipeline import Settings, make_shorts

        settings = Settings.from_env(None)  # 키는 config가 읽은 .env·서버 환경 변수에서 그대로 가져온다
    except Exception as e:  # 설정값 오타 등. 리포트는 이미 올라가 있으니 알림만 보낸다
        print(f"숏츠 설정 오류: {type(e).__name__}: {e}")
        send_text_private(f"⚠️ {date} 숏츠 실패\n\n설정 오류: {type(e).__name__}: {e}\n\n리포트는 올라가 있습니다.")
        return "failed"
    if not settings.typecast_api_key:
        print("숏츠 건너뜀 (TYPECAST_API_KEY 없음)")
        return "skipped"
    settings.output_dir = config.OUTPUT_DIR / "shorts"
    settings.fonts_dir = _SHORTS_FONTS_DIR
    if not os.environ.get("POLL_TIMEOUT_SEC"):
        settings.poll_timeout_sec = _SHORTS_SCENE_TIMEOUT_SECONDS
    if not os.environ.get("YOUTUBE_PRIVACY_STATUS"):
        # 코드 기본값(n8n과 같음)은 공개 + 구독자 알림이라, 서버에서 일부러 정하지 않았으면 비공개로 올린다
        settings.youtube_privacy_status = "private"

    RUN_STATE["step"] = "shorts"
    print("숏츠 생성 중...")
    out = {}

    def _run():
        try:
            out["video"] = make_shorts(pdf_path, settings)
        except Exception as e:
            out["error"] = e
            out["traceback"] = traceback.format_exc()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=_SHORTS_TIMEOUT_SECONDS)

    if worker.is_alive():
        print(f"숏츠가 {_SHORTS_TIMEOUT_SECONDS}초 넘게 끝나지 않아 기다리지 않고 끝냅니다.")
        send_text_private(f"⚠️ {date} 숏츠 실패\n\n{_SHORTS_TIMEOUT_SECONDS // 60}분 넘게 끝나지 않았습니다. 리포트는 올라가 있습니다.")
        return "timeout"
    if "error" in out:
        print("숏츠 생성 중 오류 발생:")
        print(out["traceback"])
        e = out["error"]
        send_text_private(f"⚠️ {date} 숏츠 실패\n\n{type(e).__name__}: {e}\n\n리포트는 올라가 있습니다.")
        return "failed"

    video = out["video"]
    if not video.youtube_video_id:
        print(f"숏츠 영상만 만들었습니다 (유튜브 업로드 꺼짐): {video.video_path}")
        return "no_upload"
    url = f"https://youtube.com/shorts/{video.youtube_video_id}"
    try:
        # 같은 날짜로 다시 올려 숏츠 주소만 붙인다. 카드를 보내지 않아 썸네일은 그대로 둔다
        post_report(pdf_path, None, RUN_STATE["context"], youtube_url=url)
    except Exception as e:
        send_text_private(f"⚠️ {date} 숏츠는 올렸지만 사이트에 주소를 붙이지 못했습니다\n\n{url}\n{type(e).__name__}: {e}")
        return "link_failed"
    print(f"숏츠 업로드·연결 완료: {url}")
    send_text_private(f"🎬 {date} 숏츠 업로드 완료\n{url}")
    return "uploaded"


def main():
    today = datetime.now()
    print(f"=== {today.isoformat()} 실행 시작 ===")

    if not is_krx_trading_day(today):
        print("오늘은 한국거래소 휴장일입니다. 건너뜁니다.")
        return

    print("네트워크 연결 확인 중...")
    if not _wait_for_network():
        print(f"{_NETWORK_WAIT_MAX_SECONDS}초 대기했지만 네트워크가 안 붙었습니다. 오늘은 건너뜁니다.")
        send_text_private(
            f"🚨 {today.strftime('%Y-%m-%d')} 자동실행 실패\n\n"
            f"{_NETWORK_WAIT_MAX_SECONDS}초 기다려도 인터넷 연결이 안 됐습니다.\n"
            f"서버 네트워크 확인이 필요합니다."
        )
        _post_run("FAILED", today, "network", f"{_NETWORK_WAIT_MAX_SECONDS}초 기다려도 인터넷 연결이 안 됐습니다.")
        return
    print("네트워크 연결 확인됨")
    send_text_private(f"🟢 {today.strftime('%Y-%m-%d %H:%M')} 자동실행 시작됨")

    result = {}

    def _run():
        try:
            result["pdf_path"] = run_auto()
        except Exception as e:
            result["error"] = e
            result["traceback"] = traceback.format_exc()

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=_PIPELINE_TIMEOUT_SECONDS)

    if worker.is_alive():
        print(f"{_PIPELINE_TIMEOUT_SECONDS}초 넘게 응답이 없어 강제 종료합니다.")
        send_text_private(
            f"🚨 {today.strftime('%Y-%m-%d')} 자동실행 실패\n\n"
            f"{_PIPELINE_TIMEOUT_SECONDS // 60}분 넘게 멈춰있어 강제 종료했습니다.\n"
            f"리포트가 생성되지 않았습니다. 서버 로그(~/report_generator/logs/auto.log) 확인이 필요합니다."
        )
        # 멈춘 스레드는 세울 수 없어 기록을 만든 뒤에도 업로드·사용량이 바뀔 수 있다. 그래서 기록 작성 시점 값이라고 적는다
        _post_run(
            "FAILED", today, RUN_STATE["step"],
            f"{_PIPELINE_TIMEOUT_SECONDS}초 넘게 멈춰 강제 종료했습니다. 업로드 여부·사용량은 기록 작성 시점 값이라 그 뒤의 변화는 빠졌을 수 있습니다.",
        )
        os._exit(1)  # 멈춘 백그라운드 스레드(네트워크 호출 등)까지 통째로 강제 종료

    if "error" in result:
        print("자동 실행 중 오류 발생:")
        print(result["traceback"])
        e = result["error"]
        send_text_private(
            f"🚨 {today.strftime('%Y-%m-%d')} 자동실행 실패\n\n"
            f"{type(e).__name__}: {e}\n\n"
            f"리포트가 생성되지 않았습니다. 서버 로그(~/report_generator/logs/auto.log) 확인이 필요합니다."
        )
        _post_run("FAILED", today, RUN_STATE["step"], f"{type(e).__name__}: {e}")
        sys.exit(1)

    shorts = _run_shorts(today, result["pdf_path"])
    _post_run("SUCCEEDED", today, shorts=shorts)
    print(f"완료: {result['pdf_path']} (숏츠: {shorts})")


if __name__ == "__main__":
    main()
