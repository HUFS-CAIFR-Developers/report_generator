import json

from openai import OpenAI

import config
from analysis.prompt_loader import load_prompt
from analysis.text_utils import strip_markdown_heading, to_word_paragraphs

_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.OPENAI_TIMEOUT_SECONDS)

_NO_MARKDOWN_RULE = (
    "마크다운 굵게/기울임 문법(**, * , # 헤더), 번호, 글머리표, 이모지를 쓰지 않는다."
)

_TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "dominant_topic": {"type": "string"},
        "summary": {"type": "string"},
        "market_direction": {"type": "string", "enum": ["positive", "negative", "mixed"]},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "related_sectors": {"type": "array", "items": {"type": "string"}},
        "supporting_headlines": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": [
        "dominant_topic", "summary", "market_direction",
        "keywords", "related_sectors", "supporting_headlines", "reason",
    ],
    "additionalProperties": False,
}

_TOPIC_PROMPT = load_prompt("market_topic")
_BRIEFING_PROMPT = load_prompt("market_briefing")


def _text(resp) -> str:
    return strip_markdown_heading(resp.output_text.strip())


def identify_dominant_topic(headlines: list[str]) -> dict:
    """오늘의 경제면 헤드라인 목록에서 반복적으로 등장하는 핵심 이슈를 구조화된 형태로 뽑아낸다."""
    headlines_text = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
    resp = _client.responses.create(
        model=config.MODEL_STANDARD,
        max_output_tokens=1500,
        input=[{"role": "user", "content": _TOPIC_PROMPT.format(headlines_text=headlines_text)}],
        text={"format": {"type": "json_schema", "name": "dominant_topic", "schema": _TOPIC_SCHEMA, "strict": True}},
    )
    topic = json.loads(resp.output_text)
    topic["headlines_text"] = headlines_text
    return topic


def write_market_briefing(topic: dict) -> str:
    """오늘의 핵심 이슈(topic)를 바탕으로 4문단짜리 시황 브리핑을 작성한다."""
    resp = _client.responses.create(
        model=config.MODEL_STANDARD,
        max_output_tokens=2000,
        input=[{
            "role": "user",
            "content": _BRIEFING_PROMPT.format(
                dominant_topic=topic["dominant_topic"],
                summary=topic["summary"],
                market_direction=topic["market_direction"],
                keywords=", ".join(topic["keywords"]),
                related_sectors=", ".join(topic["related_sectors"]),
                supporting_headlines=", ".join(topic["supporting_headlines"]),
                reason=topic["reason"],
                headlines_text=topic["headlines_text"],
                no_markdown=_NO_MARKDOWN_RULE,
            ),
        }],
    )
    return to_word_paragraphs(_text(resp))
