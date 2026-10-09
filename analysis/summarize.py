from openai import OpenAI

import config
from analysis.prompt_loader import load_prompt
from analysis.text_utils import strip_markdown_heading, to_word_paragraphs

_client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=config.OPENAI_TIMEOUT_SECONDS)


def _text(resp) -> str:
    return strip_markdown_heading(resp.output_text.strip())


_NO_MARKDOWN_RULE = "마크다운 문법(#, *, -, 볼드체 등)이나 소제목을 쓰지 말고 순수 텍스트 문장으로만 작성한다."

_SUMMARY_PROMPT = load_prompt("article_summary")
_KEY_SENTENCE_PROMPT = load_prompt("key_sentence")


def summarize_article(content: str) -> str:
    resp = _client.responses.create(
        model=config.MODEL_LIGHT,
        max_output_tokens=2000,
        input=[{"role": "user", "content": _SUMMARY_PROMPT.format(content=content, no_markdown=_NO_MARKDOWN_RULE)}],
    )
    return to_word_paragraphs(_text(resp))


def extract_key_sentence(text: str) -> str:
    resp = _client.responses.create(
        model=config.MODEL_LIGHT,
        max_output_tokens=300,
        input=[{"role": "user", "content": _KEY_SENTENCE_PROMPT.format(text=text, no_markdown=_NO_MARKDOWN_RULE)}],
    )
    return _text(resp)
