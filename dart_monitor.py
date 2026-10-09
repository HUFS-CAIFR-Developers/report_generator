"""launchd가 30분마다 실행하는 DART 전자공시 감시기.
관심 종목(코스피200+코스닥150, data/index_universe.csv)의 공시 중 "주요 공시"
(dart/major_keywords.txt 기준)만 골라 텔레그램으로 보낸다.
휴장일에는 아무것도 하지 않는다. 이미 보낸 공시(rcept_no)는 dart_sent_ids.json에 남겨
다시 보내지 않되, 전송이 실패한 건은 기록하지 않아 다음 실행 때 재시도한다."""
import json
import time
from datetime import datetime

import exchange_calendars as xcals

import config
from dart.client import fetch_disclosures
from dart.filters import is_major, load_keywords
from dart.universe import load_universe
from report.telegram_notify import send_text

_SENT_LOG_MAX_AGE_DAYS = 5
_WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _is_krx_trading_day(date) -> bool:
    return xcals.get_calendar("XKRX").is_session(date.strftime("%Y-%m-%d"))


def _load_sent_log() -> dict:
    if not config.DART_SENT_LOG.exists():
        return {}
    return json.loads(config.DART_SENT_LOG.read_text(encoding="utf-8"))


def _save_sent_log(log: dict):
    cutoff = time.time() - _SENT_LOG_MAX_AGE_DAYS * 86400
    pruned = {rcept_no: sent_at for rcept_no, sent_at in log.items() if sent_at >= cutoff}
    config.DART_SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    config.DART_SENT_LOG.write_text(json.dumps(pruned, ensure_ascii=False), encoding="utf-8")


def _format_date_header(rcept_dt: str) -> str:
    d = datetime.strptime(rcept_dt, "%Y%m%d")
    weekday = _WEEKDAY_KO[d.weekday()]
    return f"📢 금일 DART 공시_{d.strftime('%y.%m.%d')}({weekday})"


def _format_message(row: dict, corp_name: str, index_name: str) -> str:
    title = row["report_nm"].strip()
    url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"
    return (
        f"{_format_date_header(row['rcept_dt'])}\n\n"
        f"[{index_name}] {corp_name}({row['stock_code']})\n"
        f"{title}\n"
        f"제출인: {row.get('flr_nm', '-')}\n\n"
        f"자세한 내용은 아래 링크를 통해 확인하세요\n"
        f"{url}"
    )


def main():
    today = datetime.now()
    if not _is_krx_trading_day(today):
        print("휴장일입니다. 건너뜁니다.")
        return
    if not (8 <= today.hour <= 19):
        print("공시 감시 시간(08~19시)이 아닙니다. 건너뜁니다.")
        return

    universe = load_universe()
    keywords = load_keywords()
    sent_log = _load_sent_log()

    date_str = today.strftime("%Y%m%d")
    disclosures = fetch_disclosures(date_str)
    print(f"오늘 전체 공시 {len(disclosures)}건 조회")

    sent_count = 0
    for row in disclosures:
        rcept_no = row["rcept_no"]
        if rcept_no in sent_log:
            continue

        stock_code = row.get("stock_code", "").strip()
        info = universe.get(stock_code)
        if info is None:
            continue
        if not is_major(row["report_nm"], keywords):
            continue

        message = _format_message(row, info["corp_name"], info["index"])
        if send_text(message):
            sent_log[rcept_no] = time.time()
            sent_count += 1
        else:
            print(f"전송 실패, 다음 실행 때 재시도: {info['corp_name']} {row['report_nm'].strip()}")

    _save_sent_log(sent_log)
    print(f"신규 주요 공시 {sent_count}건 전송")


if __name__ == "__main__":
    main()
