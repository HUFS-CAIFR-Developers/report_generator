import json

from openai import OpenAI

import config
from analysis.prompt_loader import load_prompt
from data.krx_master import load_krx_master, match_company

_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.OPENAI_TIMEOUT_SECONDS)

_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["companies"],
    "additionalProperties": False,
}

_PROMPT = load_prompt("company_pick")


def _call_llm(content: str, exclude: list[str] | None = None) -> list[dict]:
    exclude_clause = ""
    if exclude:
        exclude_clause = f"단, 다음 기업은 이미 검토했으니 제외하고 다른 기업으로 선정하라: {', '.join(exclude)}\n"

    resp = _client.responses.create(
        model=config.MODEL_STANDARD,
        max_output_tokens=2000,
        input=[{"role": "user", "content": _PROMPT.format(content=content, exclude_clause=exclude_clause)}],
        text={"format": {"type": "json_schema", "name": "companies", "schema": _SCHEMA, "strict": True}},
    )
    return json.loads(resp.output_text)["companies"]


def pick_companies(article_content: str) -> list[dict]:
    """기사 본문 → LLM이 기업명 3개 추론 → KRX 마스터와 로컬 매칭.

    반환: [{"llm_name": ..., "corp_name": ..., "ticker": ..., "reason": ...}, ...]
    매칭 실패한 기업은 결과에서 제외된다.
    """
    master = load_krx_master()

    candidates = _call_llm(article_content)
    matched = []
    failed_names = []

    for c in candidates:
        m = match_company(c["name"], master=master)
        if m is None:
            failed_names.append(c["name"])
            continue
        matched.append({"llm_name": c["name"], "corp_name": m["corp_name"], "ticker": m["ticker"], "reason": c["reason"]})

    if len(matched) < 3 and failed_names:
        retry_candidates = _call_llm(article_content, exclude=failed_names)
        for c in retry_candidates:
            if len(matched) >= 3:
                break
            if any(c["name"] == m["llm_name"] for m in matched):
                continue
            m = match_company(c["name"], master=master)
            if m is None:
                continue
            matched.append({"llm_name": c["name"], "corp_name": m["corp_name"], "ticker": m["ticker"], "reason": c["reason"]})

    return matched[:3]
