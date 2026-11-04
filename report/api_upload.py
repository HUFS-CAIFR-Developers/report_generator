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

실행 기록(post_run)은 같은 서버·토큰으로 POST .../api/generator/runs 에 JSON으로 보낸다.
기록은 부가 기능이라 주소·토큰이 없으면 건너뛰고, 실패해도 로그만 남긴다.
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
    if not config.REPORT_API_URL.startswith("https://"):
        raise RuntimeError("REPORT_API_URL은 https 주소여야 합니다 (토큰이 평문으로 나가지 않게).")

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
        allow_redirects=False,  # 리다이렉트로 PDF·토큰이 다른(평문) 주소로 다시 나가지 않게
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"사이트 업로드 실패 HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def post_run(
    job: str,
    status: str,
    started_at: datetime,
    *,
    step: str | None = None,
    message: str | None = None,
    stats: dict | None = None,
    usage: list[dict] | None = None,
) -> None:
    """실행 기록 한 건을 보낸다 (job: daily_report|dart_monitor, status: SUCCEEDED|FAILED|SKIPPED). 예외를 던지지 않는다."""
    try:
        if not config.REPORT_API_URL or not config.REPORT_API_TOKEN:
            print("실행 기록 전송 건너뜀 (REPORT_API_URL/REPORT_API_TOKEN 없음)")
            return
        if not config.REPORT_API_URL.startswith("https://"):
            print("실행 기록 전송 건너뜀 (REPORT_API_URL이 https 주소가 아님)")
            return
        run = {
            "job": job,
            "status": status,
            "started_at": started_at.astimezone().isoformat(),
            "finished_at": datetime.now().astimezone().isoformat(),
            "step": step,
            "message": message[:1000] if message else None,
            "stats": stats,
            "usage": usage or [],
        }
        # 리포트 업로드 주소(.../api/generator/reports)와 같은 서버의 실행 기록 주소
        url = config.REPORT_API_URL.rstrip("/").rsplit("/", 1)[0] + "/runs"
        resp = requests.post(
            url,
            json=run,
            headers={"Authorization": f"Bearer {config.REPORT_API_TOKEN}"},
            timeout=30,
            allow_redirects=False,
        )
        if resp.status_code not in (200, 201):
            print(f"실행 기록 전송 실패 HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        print(f"실행 기록 전송 실패 (건너뜀): {type(e).__name__}: {e}")
