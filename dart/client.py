import requests

import config

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_NO_DATA_STATUS = "013"  # "조회된 데이타가 없습니다" - 휴장일 등 정상적으로 공시가 없는 경우


def fetch_disclosures(date: str) -> list:
    """date(YYYYMMDD)에 접수된 전체 시장의 공시 목록을 페이지네이션하며 모두 가져온다."""
    results = []
    page_no = 1
    while True:
        resp = requests.get(
            LIST_URL,
            params={
                "crtfc_key": config.OPENDART_API_KEY,
                "bgn_de": date,
                "end_de": date,
                "page_no": page_no,
                "page_count": 100,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if data["status"] == _NO_DATA_STATUS:
            break
        if data["status"] != "000":
            raise RuntimeError(f"DART API 오류: {data['status']} {data.get('message')}")

        results.extend(data["list"])
        if page_no >= data["total_page"]:
            break
        page_no += 1

    return results
