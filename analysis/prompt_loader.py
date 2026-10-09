import config

_PROMPTS_DIR = config.BASE_DIR / "prompts"
_MARKER = "<<<PROMPT>>>"


def load_prompt(name: str) -> str:
    """prompts/{name}.txt 를 읽어온다. 파일 맨 위 안내문(자리표시자 설명)은
    <<<PROMPT>>> 구분선으로 분리되어 있고, 그 아래 실제 프롬프트 본문만 반환한다."""
    path = _PROMPTS_DIR / f"{name}.txt"
    text = path.read_text(encoding="utf-8")
    if _MARKER in text:
        # 안내문 설명 중에 구분자 이름이 우연히 다시 언급되는 경우를 대비해,
        # 실제 구분선은 "마지막으로 등장하는 위치"로 간주한다.
        text = text.rsplit(_MARKER, 1)[1]
    return text.strip("\n")
