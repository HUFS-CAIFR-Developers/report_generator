"""완성된 리포트(PDF·한 장 요약 카드·사이트에 보일 글)를 백엔드(api.caifr.com)에 올린다.
백엔드가 PDF는 비공개 R2 버킷에, 카드는 공개 버킷(files.caifr.com)에 저장하고 DB에 리포트를 만든다.
같은 날짜·카테고리를 다시 올리면 덮어쓴다 (관리자가 붙인 숏츠 주소는 유지).

요청 형식 (caifr_backend#53)
    POST {REPORT_API_URL}            기본값 https://api.caifr.com/api/generator/reports
    Authorization: Bearer <REPORT_API_TOKEN>
    multipart/form-data
        report : JSON (date, category, company, title, desc, summary, highlights[], body, published)
        file   : PDF
        card   : PNG (선택)

사이트에 올리는 것이 자동실행의 목적이라, 토큰이 없거나 실패하면 예외를 던져 실패 알림으로 이어지게 한다.
"""
import json
from datetime import datetime
from pathlib import Path

import requests

import config
from analysis.text_utils import to_plain_text


def post_report(pdf_path: Path, card_path: Path | None, context: dict, category: str = "daily") -> dict:
    if not config.REPORT_API_TOKEN:
        raise RuntimeError("REPORT_API_TOKEN이 없어 사이트에 올리지 못했습니다.")

    summary = to_plain_text(context["final_summary"])
    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "category": category,
        "company": context["company1"],
        "title": context["final_title"],
        "desc": summary,
        "summary": summary,
        "highlights": [to_plain_text(context["article_summary1"])],
        "body": f"{context['article_title']}\n\n{to_plain_text(context['article_content'])}",
        "published": True,
    }
    files = {
        "report": (None, json.dumps(report, ensure_ascii=False), "application/json"),
        "file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf"),
    }
    if card_path and card_path.exists():
        files["card"] = (card_path.name, card_path.read_bytes(), "image/png")

    resp = requests.post(
        config.REPORT_API_URL,
        files=files,
        headers={"Authorization": f"Bearer {config.REPORT_API_TOKEN}"},
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"사이트 업로드 실패 HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()
