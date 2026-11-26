"""리서치 보고서 → 영상 모듈 사이의 입력 계약(interface).

n8n 에서는 Form 업로드 → PDF 텍스트 추출 → `$json.text` 가 요약 노드로 들어갔다.
코드 파이프라인에서는 그 자리를 `ReportInput` 이 대신한다. 보고서 생성 코드는 아래 중
아무 형태로나 결과를 넘기면 된다.

    ReportInput.from_text("...보고서 본문...")
    ReportInput.from_file("report.pdf" | "report.md" | "report.txt" | "report.json")
    ReportInput.from_any(<str | Path | dict | text/markdown/content 속성을 가진 객체>)

JSON/dict 형식:  {"text": "<본문>", "title": "<선택>", "metadata": {...선택}}
                 ("text" 대신 "markdown" / "content" / "body" 키도 허용)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import PipelineError

_TEXT_KEYS = ("text", "markdown", "content", "body", "report")


@dataclass
class ReportInput:
    text: str
    title: str | None = None
    source: str = "inline"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise PipelineError("input", f"보고서 본문이 비어 있습니다 (source={self.source})")

    # ---------- 생성자 ----------
    @classmethod
    def from_text(cls, text: str, title: str | None = None, **metadata: Any) -> "ReportInput":
        return cls(text=text, title=title, source="inline", metadata=metadata)

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "dict") -> "ReportInput":
        text = next((data[k] for k in _TEXT_KEYS if isinstance(data.get(k), str) and data[k].strip()), None)
        if text is None:
            raise PipelineError("input", f"보고서 dict 에 본문 키({'/'.join(_TEXT_KEYS)})가 없습니다")
        return cls(
            text=text,
            title=data.get("title") or data.get("report_title"),
            source=source,
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "ReportInput":
        p = Path(path)
        if not p.is_file():
            raise PipelineError("input", f"보고서 파일이 없습니다: {p}")
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            return cls(text=extract_pdf_text(p), title=p.stem, source=str(p))
        if suffix == ".json":
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")), source=str(p))
        # .md / .txt / 그 외 텍스트
        return cls(text=p.read_text(encoding="utf-8"), title=p.stem, source=str(p))

    @classmethod
    def from_any(cls, obj: Any) -> "ReportInput":
        if isinstance(obj, ReportInput):
            return obj
        if isinstance(obj, Path):
            return cls.from_file(obj)
        if isinstance(obj, str):
            # 짧은 한 줄이고 실제 파일이 있으면 경로로 취급
            if "\n" not in obj and len(obj) < 1024 and Path(obj).is_file():
                return cls.from_file(obj)
            return cls.from_text(obj)
        if isinstance(obj, dict):
            return cls.from_dict(obj)
        for attr in _TEXT_KEYS:
            value = getattr(obj, attr, None)
            if isinstance(value, str) and value.strip():
                return cls(text=value, title=getattr(obj, "title", None), source=type(obj).__name__)
        raise PipelineError("input", f"ReportInput 으로 변환할 수 없는 타입입니다: {type(obj).__name__}")


def extract_pdf_text(path: Path) -> str:
    """n8n `Extract from File (pdf)` 대체. 페이지 텍스트를 줄바꿈으로 이어 붙인다."""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise PipelineError("extract_pdf", "pypdf 가 설치되어 있지 않습니다 (pip install pypdf)") from e
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        raise PipelineError("extract_pdf", f"PDF 텍스트 추출 실패: {e}") from e
    if not text.strip():
        raise PipelineError("extract_pdf", "PDF 에서 텍스트를 찾지 못했습니다 (스캔본이면 OCR 필요)")
    return text
