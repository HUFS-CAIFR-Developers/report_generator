"""모든 OpenAI 호출이 거치는 곳. 응답의 사용량(resp.usage)을 모델별로 모아 실행 기록(report/api_upload.post_run)에 보낸다.
한 프로세스가 한 번 실행하고 끝나므로(cron) 모은 값은 프로세스 전체에서 하나다."""
import threading

from openai import OpenAI

import config

_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.OPENAI_TIMEOUT_SECONDS)

_lock = threading.Lock()
# 모델 → [호출 수, 입력 토큰, 출력 토큰]
_usage: dict[str, list[int]] = {}


def create(**kwargs):
    """_client.responses.create와 같고, 응답을 받으면 사용량을 기록한다 (형식이 틀린 응답도 비용은 나간다)."""
    resp = _client.responses.create(**kwargs)
    add_usage(kwargs["model"], resp.usage)
    return resp


def add_usage(model: str, usage) -> None:
    # 응답의 model은 날짜가 붙은 이름일 수 있어, 단가표와 맞추려고 요청한 모델 이름으로 모은다
    with _lock:
        row = _usage.setdefault(model, [0, 0, 0])
        row[0] += 1
        row[1] += int(getattr(usage, "input_tokens", 0) or 0)
        row[2] += int(getattr(usage, "output_tokens", 0) or 0)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = config.MODEL_PRICES_USD_PER_1M.get(model)
    if prices is None:
        print(f"경고: 단가를 모르는 모델이라 비용을 0으로 기록합니다: {model} (config.MODEL_PRICES_USD_PER_1M)")
        return 0.0
    return round((prices[0] * input_tokens + prices[1] * output_tokens) / 1_000_000, 6)


def usage_snapshot() -> tuple[dict, list[dict]]:
    """실행 기록의 (stats 중 LLM 부분, usage 항목). 시간초과 때는 작업 스레드가 아직 돌 수 있어 한 번 읽은 값으로 둘 다 만든다."""
    with _lock:
        rows = {model: list(row) for model, row in _usage.items()}
    items = [
        {"model": model, "input_tokens": inp, "output_tokens": out, "cost_usd": cost_usd(model, inp, out)}
        for model, (_, inp, out) in rows.items()
    ]
    stats = {
        "llm_calls": sum(row[0] for row in rows.values()),
        "input_tokens": sum(i["input_tokens"] for i in items),
        "output_tokens": sum(i["output_tokens"] for i in items),
        "cost_usd": round(sum(i["cost_usd"] for i in items), 6),
    }
    return stats, items
