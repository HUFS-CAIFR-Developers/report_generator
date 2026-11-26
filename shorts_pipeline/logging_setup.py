from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path

LOGGER_NAME = "shorts_pipeline"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def get_logger(child: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if not child else f"{LOGGER_NAME}.{child}")


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """콘솔 + (선택) 실행별 로그 파일. 같은 프로세스에서 여러 번 불러도 핸들러가 중복되지 않는다."""
    logger = get_logger()
    logger.setLevel(level)
    logger.propagate = False
    for h in list(logger.handlers):
        if getattr(h, "_shorts_handler", False):
            logger.removeHandler(h)
            h.close()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_FORMAT, "%H:%M:%S"))
    console._shorts_handler = True  # type: ignore[attr-defined]
    logger.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(_FORMAT))
        fh._shorts_handler = True  # type: ignore[attr-defined]
        logger.addHandler(fh)
    return logger


@contextmanager
def step(name: str, logger: logging.Logger | None = None):
    """단계 시작/종료/소요시간/실패를 일관되게 기록한다."""
    log = logger or get_logger()
    log.info("▶ %s 시작", name)
    t0 = time.monotonic()
    try:
        yield
    except Exception:
        log.exception("✖ %s 실패 (%.1fs)", name, time.monotonic() - t0)
        raise
    log.info("✔ %s 완료 (%.1fs)", name, time.monotonic() - t0)
