import config


def load_keywords() -> list:
    with open(config.DART_MAJOR_KEYWORDS_FILE, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def is_major(report_nm: str, keywords: list | None = None) -> bool:
    keywords = keywords if keywords is not None else load_keywords()
    return any(kw in report_nm for kw in keywords)
