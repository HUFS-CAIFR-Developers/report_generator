import re


def to_word_paragraphs(text: str) -> str:
    """빈 줄로 구분된 문단을 docxtpl이 실제 Word 문단(<w:p>)으로 나누는
    구분자(\\a, bell 문자)로 변환한다. 문단 내부 개행은 줄바꿈(<w:br/>)으로 남는다.
    구분자를 두 번(\\a\\a) 넣어 문단 사이에 빈 문단을 하나 끼워, 문단 스타일의
    '단락 뒤 여백' 설정과 무관하게 항상 빈 줄이 보이도록 한다."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    return "\a\a".join(paragraphs)


def to_plain_text(text: str) -> str:
    """to_word_paragraphs()가 넣은 문단 구분자(\\a\\a)를 다시 일반 개행(\\n\\n)으로 되돌린다.
    LLM 프롬프트 재사용이나 API 전송처럼 Word 문서가 아닌 곳에 텍스트를 넣을 때 쓴다."""
    return text.replace("\a\a", "\n\n").replace("\a", "\n\n")


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
