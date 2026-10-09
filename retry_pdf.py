"""자동실행 중 PDF 변환이 실패(접근 권한 팝업 미응답 등)했을 때, 나중에 사람이 팝업을
눌러서 PDF가 실제로 만들어지면 그 즉시 텔레그램으로 보내는 재시도 스크립트.
launchd로 주기적으로(예: 20분마다) 돌린다. 보낼 게 없으면 아무 일도 안 하고 바로 끝난다."""
import time
from pathlib import Path

import config
from report.build_doc import export_pdf
from report.telegram_notify import send_pdf_followup

_MAX_AGE_HOURS = 12  # 이보다 오래된 docx는 그날 리포트가 아니므로 재시도 대상에서 제외


def _find_pending_docx() -> Path | None:
    """오늘 자동실행에서 나온, pdf가 아직 없고 재시도도 안 해본(sent 마커 없는) docx를 찾는다.
    오래된 파일(예전 테스트 결과 등)은 절대 건드리지 않도록 최근 것만 대상으로 한다."""
    cutoff = time.time() - _MAX_AGE_HOURS * 3600
    docs = sorted(config.OUTPUT_DIR.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    for docx in docs:
        if docx.name.startswith("~$"):
            continue  # Word가 남기는 잠금파일 - 진짜 문서가 아니므로 건너뜀
        if docx.stat().st_mtime < cutoff:
            break  # 최신순 정렬이므로 여기서부터는 전부 더 오래됨 - 더 볼 필요 없음
        pdf = docx.with_suffix(".pdf")
        sent_marker = docx.with_suffix(".pdf.sent")
        if pdf.exists() or sent_marker.exists():
            continue
        return docx
    return None


def main():
    docx = _find_pending_docx()
    if not docx:
        return

    pdf = export_pdf(docx)
    if not pdf:
        return  # 아직 권한을 안 눌렀을 수 있음 - 다음 재시도 때 다시 시도

    send_pdf_followup(pdf)
    docx.with_suffix(".pdf.sent").touch()
    print(f"지연 전송 완료: {pdf}")


if __name__ == "__main__":
    main()
