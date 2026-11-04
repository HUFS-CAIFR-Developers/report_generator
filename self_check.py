"""실행 기록 비용 계산과 DART 알림 중복 방지 저장을 네트워크 없이 확인한다. 실행: python self_check.py"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENDART_API_KEY", "test")

import config  # noqa: E402
import dart_monitor  # noqa: E402
from analysis import llm  # noqa: E402


def check_cost():
    # given: terra 2회, 단가를 모르는 모델 1회
    llm.add_usage("gpt-5.6-terra", SimpleNamespace(input_tokens=1_000_000, output_tokens=500_000))
    llm.add_usage("gpt-5.6-terra", SimpleNamespace(input_tokens=0, output_tokens=None))
    llm.add_usage("unknown-model", SimpleNamespace(input_tokens=10, output_tokens=10))

    # then: terra = 2.00 + 12.00 * 0.5, 모르는 모델은 0
    stats, usage = llm.usage_snapshot()
    items = {i["model"]: i for i in usage}
    assert items["gpt-5.6-terra"] == {"model": "gpt-5.6-terra", "input_tokens": 1_000_000, "output_tokens": 500_000, "cost_usd": 8.0}
    assert items["unknown-model"]["cost_usd"] == 0.0
    assert stats == {"llm_calls": 3, "input_tokens": 1_000_010, "output_tokens": 500_010, "cost_usd": 8.0}


def check_sent_ids_saved_per_send():
    # given: 관심 종목의 주요 공시 2건. 첫 건은 보내고 두 번째에서 프로세스가 죽는다
    rows = [
        {"rcept_no": n, "rcept_dt": "20261104", "stock_code": "005930", "report_nm": "유상증자결정", "flr_nm": "삼성전자"}
        for n in ("1", "2")
    ]
    sent, runs = [], []

    def send_once_then_die(message):
        if sent:
            raise SystemExit("중간에 죽음")
        sent.append(message)
        return True

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 4, 10, 0)

    config.DART_SENT_LOG = Path(tempfile.mkdtemp()) / "dart_sent_ids.json"
    dart_monitor.datetime = Now
    dart_monitor._is_krx_trading_day = lambda date: True
    dart_monitor.load_universe = lambda: {"005930": {"corp_name": "삼성전자", "index": "코스피200"}}
    dart_monitor.load_keywords = lambda: ["유상증자"]
    dart_monitor.is_major = lambda title, keywords: True
    dart_monitor.fetch_disclosures = lambda date: rows
    dart_monitor.post_run = lambda *args, **kwargs: runs.append((args, kwargs))
    dart_monitor.time.sleep = lambda seconds: None
    dart_monitor.send_text = send_once_then_die

    # when
    try:
        dart_monitor.main()
    except SystemExit:
        pass

    # then: 보낸 첫 건은 죽기 전에 이미 저장돼 있다
    assert set(json.loads(config.DART_SENT_LOG.read_text())) == {"1"}

    # when: 다음 실행
    sent.clear()
    dart_monitor.send_text = lambda message: sent.append(message) or True
    dart_monitor.main()

    # then: 두 번째 건만 보내고 실행 기록을 남긴다
    assert len(sent) == 1 and "rcpNo=2" in sent[0]
    assert set(json.loads(config.DART_SENT_LOG.read_text())) == {"1", "2"}
    args, kwargs = runs[-1]
    assert args[:2] == ("dart_monitor", "SUCCEEDED")
    assert kwargs["stats"] == {"scanned": 2, "matched": 1, "sent": 1, "failed_sends": 0}


if __name__ == "__main__":
    check_cost()
    check_sent_ids_saved_per_send()
    print("self_check OK")
