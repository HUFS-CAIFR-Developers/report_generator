"""launchd가 매일 아침 실행하는 진입점.
한국거래소(KRX) 개장일이 아니면(주말·공휴일) 아무것도 하지 않고 종료한다."""
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime

import exchange_calendars as xcals

from main import run_auto
from report.telegram_notify import send_text_private

_NETWORK_WAIT_MAX_SECONDS = 120
_NETWORK_WAIT_INTERVAL_SECONDS = 5

# 전체 파이프라인이 이 시간을 넘기면 어딘가 멈춘 것으로 보고 강제 종료한다.
# (2026-10-02에 OpenAI 호출 하나가 15분 넘게 응답 없이 멈췄던 적 있음 - 개별 호출
# 타임아웃(config.OPENAI_TIMEOUT_SECONDS)과 별개로, 다른 어떤 단계가 멈추든 잡아내는
# 전체 안전장치.)
_PIPELINE_TIMEOUT_SECONDS = 600


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
            f"맥이 와이파이에 붙어있는지 확인이 필요합니다."
        )
        return
    print("네트워크 연결 확인됨")
    send_text_private(f"🟢 {today.strftime('%Y-%m-%d %H:%M')} 자동실행 시작됨")

    result = {}

    def _run():
        try:
            result["out_path"], result["pdf_path"] = run_auto()
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
            f"리포트가 생성되지 않았습니다. 맥에서 로그 확인이 필요합니다."
        )
        os._exit(1)  # 멈춘 백그라운드 스레드(네트워크 호출 등)까지 통째로 강제 종료

    if "error" in result:
        print("자동 실행 중 오류 발생:")
        print(result["traceback"])
        e = result["error"]
        send_text_private(
            f"🚨 {today.strftime('%Y-%m-%d')} 자동실행 실패\n\n"
            f"{type(e).__name__}: {e}\n\n"
            f"리포트가 생성되지 않았습니다. 맥에서 로그 확인이 필요합니다."
        )
        sys.exit(1)

    print(f"완료: {result['out_path']}")
    if result.get("pdf_path"):
        print(f"PDF: {result['pdf_path']}")


if __name__ == "__main__":
    main()
