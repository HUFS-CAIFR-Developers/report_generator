import json
from dataclasses import dataclass

import pytest

from shorts_pipeline import ReportInput
from shorts_pipeline.errors import PipelineError


def test_from_text_and_any():
    r = ReportInput.from_any("보고서 본문\n두 번째 줄")
    assert r.text.startswith("보고서") and r.source == "inline"


def test_from_dict_keys():
    assert ReportInput.from_dict({"markdown": "# 제목\n본문", "title": "T"}).title == "T"
    assert ReportInput.from_dict({"content": "x", "report_title": "R"}).title == "R"
    with pytest.raises(PipelineError):
        ReportInput.from_dict({"foo": "bar"})


def test_from_files(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# 보고서\n내용", encoding="utf-8")
    js = tmp_path / "r.json"
    js.write_text(json.dumps({"text": "본문", "title": "제목", "metadata": {"k": 1}}, ensure_ascii=False), encoding="utf-8")
    assert ReportInput.from_any(str(md)).title == "r"
    r = ReportInput.from_file(js)
    assert (r.text, r.title, r.metadata) == ("본문", "제목", {"k": 1})
    with pytest.raises(PipelineError, match="파일이 없습니다"):
        ReportInput.from_file(tmp_path / "nope.pdf")


def test_from_object_with_markdown_attr():
    @dataclass
    class Report:  # 보고서 생성 코드가 돌려줄 법한 객체
        title: str
        markdown: str

    r = ReportInput.from_any(Report("제목", "본문"))
    assert (r.title, r.text) == ("제목", "본문")


def test_empty_text_rejected():
    with pytest.raises(PipelineError):
        ReportInput.from_text("   ")
