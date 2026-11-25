import re


def to_paragraphs(text: str) -> str:
    """문단 사이 빈 줄을 정확히 한 줄로 맞춘다. 문단 안 줄바꿈은 그대로 둔다 (PDF 템플릿이 빈 줄로 문단을 나눈다)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    return "\n\n".join(paragraphs)


def strip_markdown_heading(text: str) -> str:
    """모델이 지시를 무시하고 붙이는 마크다운 문법을 방어적으로 제거.
    - 앞에 붙는 헤더(# ...) 줄 제거
    - 전체를 감싸는 **볼드**/*이탤릭* 마커 제거"""
    text = text.strip()
    lines = text.split("\n")
    while lines and lines[0].strip().startswith("#"):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    text = "\n".join(lines).strip()

    for marker in ("**", "*"):
        if text.startswith(marker) and text.endswith(marker) and len(text) > 2 * len(marker):
            text = text[len(marker):-len(marker)].strip()
            break

    return text
