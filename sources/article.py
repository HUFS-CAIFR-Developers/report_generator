import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# 국내 주요 언론사/포털의 기사 본문 컨테이너 셀렉터. 네이버 뉴스가 압도적 비중을 차지해 최우선으로 둔다.
_CONTENT_SELECTORS = [
    "#dic_area",  # 네이버 뉴스
    "#newsct_article",
    "#articleBodyContents",  # 일부 언론사 네이버 제휴 페이지
    "article",
    ".article_body",
    ".news_body",
]
_TITLE_SELECTORS = ["#title_area", "h2.media_end_head_headline", "h1"]


def fetch_article(url: str) -> dict:
    """뉴스 URL에서 제목과 본문 텍스트를 추출."""
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    title = ""
    for sel in _TITLE_SELECTORS:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()

    content = ""
    for sel in _CONTENT_SELECTORS:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                content = text
                break

    if not content:
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        content = "\n".join(p for p in paragraphs if p)

    if not content:
        content = soup.get_text(separator="\n", strip=True)

    return {"title": title, "content": content}
