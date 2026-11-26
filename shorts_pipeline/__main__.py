"""CLI: python -m shorts_pipeline <보고서 파일(.pdf/.md/.txt/.json)> [--text "..."]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, Settings
from .errors import PipelineError
from .interface import ReportInput
from .logging_setup import setup_logging
from .pipeline import ShortsPipeline


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shorts_pipeline", description="보고서 → 쇼츠 영상 자동 생성")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("report", nargs="?", help="보고서 파일 (.pdf / .md / .txt / .json)")
    src.add_argument("--text", help="보고서 본문을 직접 전달")
    src.add_argument("--stdin", action="store_true", help="표준입력에서 보고서 본문(또는 JSON) 읽기")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--output-dir")
    ap.add_argument("--keep-temp", action="store_true")
    ap.add_argument("--run-name", help="output/runs/<run-name> 폴더 이름")
    ap.add_argument("--no-upload", action="store_true", help="영상만 만들고 YouTube 에 올리지 않음")
    args = ap.parse_args(argv)

    setup_logging()
    try:
        settings = Settings.from_env(args.env_file)
        if args.output_dir:
            settings.output_dir = Path(args.output_dir)
        if args.keep_temp:
            settings.keep_temp = True
        if args.no_upload:
            settings.youtube_upload = False

        if args.text:
            report = ReportInput.from_text(args.text)
        elif args.stdin:
            data = sys.stdin.read()
            try:
                report = ReportInput.from_dict(json.loads(data), source="stdin")
            except (json.JSONDecodeError, TypeError, AttributeError):
                report = ReportInput(text=data, source="stdin")
        else:
            report = ReportInput.from_file(args.report)

        result = ShortsPipeline(settings).run(report, run_name=args.run_name)
    except (ConfigError, PipelineError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
