"""HTML 템플릿으로 리포트 PDF를 만든다.

main.py가 만든 context·chart_paths를 받아 report/html/template.html을 채운 뒤
크롬 headless로 PDF를 인쇄한다. 글꼴·줄 간격·쪽 나누기를 CSS로 정해 서버·PC 어디서 만들어도 모양이 같다.
PDF는 사이트에 올리는 결과물이라 실패하면 예외를 던져 자동실행 실패 알림으로 이어지게 한다.

미리보기: python -m report.html.build_html <context.json> <차트 폴더> <출력.pdf>
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

HTML_DIR = Path(__file__).resolve().parent

TECH_CHARTS = [
    ("rsi", "최근 3개월 RSI 데이터 차트"),
    ("stoch", "최근 3개월 STOCH RSI 데이터 차트"),
    ("vol", "20일 거래량대비 변화율 차트"),
    ("boll", "최근 3개월 볼린저밴드 차트"),
    ("ma", "최근 3개월 Moving average 차트"),
    ("macd", "최근 3개월 MACD 차트"),
]

_CHROME_CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    "chromium", "chromium-browser", "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _paras(text: str) -> Markup:
    """빈 줄로 문단을 나누고, 문단 안의 줄바꿈은 그대로 둔다 (기술적 분석 목록)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    return Markup("\n".join(f"<p>{escape(b)}</p>" for b in blocks))


def _companies(context: dict, chart_paths: dict[str, Path]) -> list[dict]:
    companies = []
    picked = [i for i in (1, 2, 3) if context.get(f"company{i}")]
    for i in picked:
        # 그림 번호: 일봉 차트(종목 수만큼) 다음부터 종목마다 기술 차트 6개
        charts = [
            {"no": len(picked) + (i - 1) * 6 + n, "label": label, "src": Path(chart_paths[f"chart{i}_tech_{key}"]).as_uri()}
            for n, (key, label) in enumerate(TECH_CHARTS, start=1)
        ]
        companies.append({
            "name": context[f"company{i}"],
            "ticker": context[f"company{i}_ticker"],
            "summary": context.get(f"company{i}_summary", ""),
            "content": context.get(f"company{i}_content", ""),
            "tec_summary": context.get(f"company{i}_tec_summary", ""),
            "tec_content": context.get(f"company{i}_tec_content", ""),
            "chart": Path(chart_paths[f"chart{i}"]).as_uri(),
            "tech_rows": [charts[0:2], charts[2:4], charts[4:6]],
        })
    return companies


def render_html(context: dict, chart_paths: dict[str, Path]) -> str:
    env = Environment(loader=FileSystemLoader(HTML_DIR), autoescape=select_autoescape(["html"]))
    env.filters["paras"] = _paras
    html = env.get_template("template.html").render(**context, companies=_companies(context, chart_paths))
    # 임시 폴더에서 열어도 CSS·로고를 찾도록 기준 경로를 템플릿 폴더로 둔다
    return html.replace("<head>", f'<head>\n<base href="{HTML_DIR.as_uri()}/">', 1)


def _chrome() -> str:
    for c in _CHROME_CANDIDATES:
        if c and (shutil.which(c) or Path(c).exists()):
            return c
    raise RuntimeError("크롬(Chromium)을 찾을 수 없습니다. CHROME_BIN 환경 변수로 경로를 지정하세요.")


def export_pdf(context: dict, chart_paths: dict[str, Path], pdf_path: Path) -> Path:
    pdf_path.unlink(missing_ok=True)  # 같은 이름의 예전 PDF가 결과로 잘못 쓰이지 않게 한다
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "report.html"
        html_path.write_text(render_html(context, chart_paths), encoding="utf-8")
        subprocess.run(
            [_chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-pdf-header-footer",
             "--allow-file-access-from-files", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
            check=True, capture_output=True, timeout=180,
        )
    if not pdf_path.exists():
        raise RuntimeError(f"PDF 변환 결과가 없습니다: {pdf_path}")
    return pdf_path


if __name__ == "__main__":
    ctx_file, chart_dir, out = sys.argv[1:4]
    ctx = json.loads(Path(ctx_file).read_text(encoding="utf-8"))
    charts = {p.stem: p for p in Path(chart_dir).glob("*.png")}
    Path(out).with_suffix(".html").write_text(render_html(ctx, charts), encoding="utf-8")
    print(export_pdf(ctx, charts, Path(out).resolve()))
