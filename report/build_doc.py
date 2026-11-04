import io
import re
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm

import config


def _safe_filename_part(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text)[:20] or "report"


# 템플릿 표 셀 실측 폭: 메인 가격차트는 180mm 폭 표, 보조 지표차트는 90mm 폭 2열 표.
# 셀 테두리에 딱 붙지 않도록 여유를 조금 두고 삽입한다.
_MAIN_CHART_WIDTH = Mm(170)
_SUB_CHART_WIDTH = Mm(85)

_PROOF_ERR_RE = re.compile(r"<w:proofErr\b[^>]*/>")


def _chart_width(key: str):
    return _MAIN_CHART_WIDTH if re.fullmatch(r"chart\d+", key) else _SUB_CHART_WIDTH


def _strip_proof_errors(template_path: Path) -> io.BytesIO:
    """Word 맞춤법 검사기가 {{placeholder}} 중간에 끼워넣는 <w:proofErr/> 마커를 제거한
    docx를 메모리 상에서 새로 만들어 반환한다. 이 마커가 태그를 여러 run으로 쪼개면
    docxtpl이 일부 태그를 인식하지 못해 미치환/문서손상으로 이어질 수 있다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(template_path) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                text = data.decode("utf-8")
                text = _PROOF_ERR_RE.sub("", text)
                data = text.encode("utf-8")
            dst.writestr(item, data)
    buf.seek(0)
    return buf


def build_report(context: dict, chart_paths: dict[str, Path]) -> Path:
    """context에 텍스트 값, chart_paths에 {placeholder_key: png_path}를 넣으면
    report/template.docx를 채운 결과 .docx를 output/에 저장하고 경로를 반환."""
    if not config.TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"템플릿 파일이 없습니다: {config.TEMPLATE_PATH}\n"
            "report/template.docx 경로에 사용자가 만든 양식 파일을 넣어주세요."
        )

    cleaned = _strip_proof_errors(config.TEMPLATE_PATH)
    doc = DocxTemplate(cleaned)

    full_context = dict(context)
    for key, path in chart_paths.items():
        full_context[key] = InlineImage(doc, str(path), width=_chart_width(key))

    # autoescape=False가 기본값이라 본문에 '<', '>', '&' 같은 문자가 그대로 들어가면
    # (예: "MA5<MA20<MA60" 같은 비교 표기) XML 태그로 오인되어 문서가 손상된다.
    doc.render(full_context, autoescape=True)

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    company_part = _safe_filename_part(context.get("company1", "report"))
    out_path = config.OUTPUT_DIR / f"{stamp}_{company_part}_report.docx"
    doc.save(str(out_path))
    return out_path


def export_pdf(docx_path: Path) -> Path:
    """생성된 .docx를 같은 폴더에 같은 이름의 .pdf로 내보낸다 (LibreOffice headless).
    서버(Docker)에는 템플릿 글꼴(나눔바른고딕, 맑은 고딕→나눔바른고딕 대체)을 넣어 두었다 (Dockerfile 참고).
    PDF는 사이트에 올리는 결과물이라 실패하면 예외를 던져 자동실행 실패 알림으로 이어지게 한다."""
    pdf_path = docx_path.with_suffix(".pdf")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
        check=True, capture_output=True, timeout=180,
    )
    if not pdf_path.exists():
        raise RuntimeError(f"PDF 변환 결과가 없습니다: {pdf_path}")
    return pdf_path
