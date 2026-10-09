import json

import pandas as pd
from openai import OpenAI

import config
from analysis.prompt_loader import load_prompt
from analysis.text_utils import strip_markdown_heading, to_word_paragraphs

_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.OPENAI_TIMEOUT_SECONDS)


def _text(resp) -> str:
    return strip_markdown_heading(resp.output_text.strip())


_NO_MARKDOWN_RULE = (
    "마크다운 굵게/기울임 문법(**, * , # 헤더)은 쓰지 않는다. "
    "번호(1. 2. ...)와 하이픈(-) 목록은 일반 텍스트 기호로는 사용해도 된다."
)

_STYLE_RULE = """[문체 통일 규칙]
- 모든 문장은 뉴스 기사에서 사용하는 평서체로 작성한다.
- 문장 끝은 ~했다, ~이다, ~된다, ~보인다, ~전망이다 등으로 통일한다."""

_INVESTMENT_PROMPT = load_prompt("investment_analysis")
_TECH_PROMPT = load_prompt("technical_analysis")
_ONE_SENTENCE_PROMPT = load_prompt("one_sentence_conclusion")
_REPORT_TITLE_PROMPT = load_prompt("report_title")
_FINAL_PROMPT = load_prompt("final_title_summary")

_TITLE_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

_FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "final_title": {"type": "string"},
        "final_summary": {"type": "string"},
    },
    "required": ["final_title", "final_summary"],
    "additionalProperties": False,
}


def write_investment_analysis(corp_name: str, ticker: str, reason: str, article_summary: str) -> str:
    resp = _client.responses.create(
        model=config.MODEL_STANDARD,
        max_output_tokens=2000,
        input=[{
            "role": "user",
            "content": _INVESTMENT_PROMPT.format(
                corp_name=corp_name, ticker=ticker, reason=reason, article_summary=article_summary,
                no_markdown=_NO_MARKDOWN_RULE,
            ),
        }],
    )
    return to_word_paragraphs(_text(resp))


def write_technical_analysis(corp_name: str, ticker: str, technical_data: pd.DataFrame) -> str:
    recent = technical_data.tail(config.TECH_CHART_LOOKBACK_DAYS)
    tech_csv = recent.to_csv(index=False)
    resp = _client.responses.create(
        model=config.MODEL_STANDARD,
        max_output_tokens=3000,
        input=[{
            "role": "user",
            "content": _TECH_PROMPT.format(
                corp_name=corp_name, ticker=ticker, tech_csv=tech_csv, no_markdown=_NO_MARKDOWN_RULE
            ),
        }],
    )
    return to_word_paragraphs(_text(resp))


def one_sentence_conclusion(text: str) -> str:
    resp = _client.responses.create(
        model=config.MODEL_LIGHT,
        max_output_tokens=300,
        input=[{
            "role": "user",
            "content": _ONE_SENTENCE_PROMPT.format(text=text, style_rule=_STYLE_RULE, no_markdown=_NO_MARKDOWN_RULE),
        }],
    )
    return _text(resp)


def generate_report_title(full_text: str) -> str:
    resp = _client.responses.create(
        model=config.MODEL_STANDARD,
        max_output_tokens=500,
        input=[{"role": "user", "content": _REPORT_TITLE_PROMPT.format(text=full_text)}],
        text={"format": {"type": "json_schema", "name": "report_title", "schema": _TITLE_SCHEMA, "strict": True}},
    )
    title = json.loads(resp.output_text)["title"].strip()
    return title[:12]


def generate_final_title_summary(full_text: str) -> tuple[str, str]:
    resp = _client.responses.create(
        model=config.MODEL_LIGHT,
        max_output_tokens=1000,
        input=[{"role": "user", "content": _FINAL_PROMPT.format(text=full_text)}],
        text={"format": {"type": "json_schema", "name": "final_title_summary", "schema": _FINAL_SCHEMA, "strict": True}},
    )
    data = json.loads(resp.output_text)
    return data["final_title"], data["final_summary"]
