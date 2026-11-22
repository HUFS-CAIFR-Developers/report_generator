"""완성된 리포트 PDF → 쇼츠 영상 → YouTube 업로드 (shorts_pipeline).

예전에는 리포트 PDF를 사람이 직접 쇼츠 코드에 넣어야 했다. 이제 main.py·run_auto.py가
리포트를 만든 뒤 바로 이 함수를 부른다. 쇼츠 입력은 예전과 똑같이 PDF에서 뽑은 텍스트다.
"""
from pathlib import Path

import config
from shorts_pipeline import ReportInput, Settings, ShortsPipeline, VideoResult


def make_report_shorts(pdf_path: Path, *, upload: bool | None = None) -> VideoResult:
    """upload=None이면 .env의 YOUTUBE_UPLOAD(기본 true)를 따른다. 실패하면 예외를 던진다."""
    settings = Settings.from_env(config.BASE_DIR / ".env")
    settings.output_dir = config.SHORTS_OUTPUT_DIR
    settings.fonts_dir = config.SHORTS_FONTS_DIR
    if upload is not None:
        settings.youtube_upload = upload

    pdf_path = Path(pdf_path)
    report = ReportInput.from_file(pdf_path)
    # 실행 기록은 output/shorts/runs/<리포트 파일명>/ 에 남겨 어느 리포트의 쇼츠인지 바로 알 수 있게 한다
    return ShortsPipeline(settings).run(report, run_name=pdf_path.stem)


def shorts_url(result: VideoResult) -> str | None:
    return f"https://youtube.com/shorts/{result.youtube_video_id}" if result.youtube_video_id else None
