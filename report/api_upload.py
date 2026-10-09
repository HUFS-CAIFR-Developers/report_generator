"""외부 서버(api.caifr.com)에 완성된 PDF 파일 자체를 multipart/form-data로 업로드한다.
서버가 이 PDF를 그대로 AWS S3에 저장하므로, 이쪽에서 S3나 AWS 키를 직접 다룰 필요는 없다.

서버 개발자가 Authorization 토큰 체크를 붙일 예정(openssl rand -hex 32로 발급)이라,
토큰은 .env의 REPORT_API_TOKEN에 넣으면 Bearer 토큰으로 실어 보낸다. 토큰이 아직 없거나
PDF가 없으면(권한 팝업 미응답 등) 그냥 건너뛴다 - 이 업로드는 선택 기능이라 실패해도
전체 파이프라인은 안 끊긴다.

요청 형식 (서버 계약)
    POST {REPORT_API_URL}
    Content-Type: multipart/form-data
    Authorization: Bearer <token>

    file        : PDF 파일 바이너리 (application/pdf)
    title       : 보고서 제목
    report_date : YYYY-MM-DD
    category    : 보고서 종류 (이 프로젝트는 매일 시황 리포트 하나뿐이라 "daily" 고정)
    company     : 관련 기업명 (선택 - 여러 개면 쉼표로 나열)

파일명은 서버 권장 규칙(YYYYMMDD-report-name.pdf)을 따른다.
"""
from datetime import datetime
from pathlib import Path

import requests

import config


def _upload_filename(report_date: str, category: str) -> str:
    return f"{report_date.replace('-', '')}-{category}-report.pdf"


def post_report(pdf_path: Path | None, context: dict, companies: list[dict], category: str = "daily") -> bool:
    if not config.REPORT_API_TOKEN:
        print("REPORT_API_TOKEN 미설정 - 서버 업로드 건너뜀")
        return False
    if not pdf_path or not pdf_path.exists():
        print("PDF 파일이 없어 서버 업로드 건너뜀 (권한 팝업 미응답 등으로 PDF 변환 실패 가능성)")
        return False

    report_date = datetime.now().strftime("%Y-%m-%d")
    filename = _upload_filename(report_date, category)

    data = {
        "title": context["title"],
        "report_date": report_date,
        "category": category,
        "company": ", ".join(c["corp_name"] for c in companies),
    }
    headers = {"Authorization": f"Bearer {config.REPORT_API_TOKEN}"}

    try:
        with open(pdf_path, "rb") as f:
            files = {"file": (filename, f, "application/pdf")}
            resp = requests.post(config.REPORT_API_URL, data=data, files=files, headers=headers, timeout=60)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"서버 업로드 실패 (건너뜀): {e}")
        return False
