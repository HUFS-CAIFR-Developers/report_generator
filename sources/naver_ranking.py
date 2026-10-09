import requests
from bs4 import BeautifulSoup

_URL = "https://news.naver.com/section/101"  # 네이버 뉴스 경제면
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_economy_headlines() -> list[str]:
    """네이버 뉴스 경제면에 노출된 기사 제목을 전부 가져온다."""
    resp = requests.get(_URL, headers=_HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    titles = [a.get_text(strip=True) for a in soup.select("a.sa_text_title")]
    return [t for t in titles if t]
