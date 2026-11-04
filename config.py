import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENDART_API_KEY = os.environ["OPENDART_API_KEY"]

# 텔레그램 전송은 선택 기능이라 없어도 파이프라인은 돌아간다 (report/telegram_notify.py 참고).
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# docx 원본을 매일 보내는 비공개 채널 (사용자 본인만 보는 용도 - PDF 변환은 본인이 직접).
TELEGRAM_DOCX_CHAT_ID = os.environ.get("TELEGRAM_DOCX_CHAT_ID")

# 사이트 업로드 (caifr_backend#53, report/api_upload.py). 토큰은 서버 deploy/.env.app의
# REPORT_GENERATOR_TOKEN과 같은 값.
REPORT_API_URL = os.environ.get("REPORT_API_URL", "https://api.caifr.com/api/generator/reports")
REPORT_API_TOKEN = os.environ.get("REPORT_API_TOKEN")
REPORT_AUTHOR = "제갈민찬"

# 역할별 OpenAI 모델. 품질/비용 균형이 안 맞으면 여기만 바꾸면 됨.
MODEL_LIGHT = "gpt-5.6-luna"     # 요약, 핵심 문장 추출, 제목 등 단순 작업
MODEL_STANDARD = "gpt-5.6-terra"  # 기업 선정, 투자분석/기술적분석 본문 등 품질 중요 작업

# OpenAI 호출이 비정상적으로 오래 걸려서 자동실행이 멈춰버린 적 있음(2026-10-02).
# 이 시간을 넘기면 예외를 던지도록 모든 OpenAI 클라이언트에 적용한다.
OPENAI_TIMEOUT_SECONDS = 90

KRX_MASTER_CACHE = BASE_DIR / "data" / "krx_master_cache.csv"
KRX_MASTER_MAX_AGE_DAYS = 7

# DART 주요공시 텔레그램 알림 (dart_monitor.py) 관련 경로.
# INDEX_UNIVERSE_CSV는 코스피200+코스닥150 구성종목 스냅샷 - 6개월마다(6월·12월 리밸런싱)
# 갱신 필요 (data/index_universe_meta.json 참고). DART_MAJOR_KEYWORDS_FILE은 "주요 공시"
# 판단 기준 키워드 목록 - 코드 안 건드리고 이 파일만 고치면 기준을 바꿀 수 있음.
INDEX_UNIVERSE_CSV = BASE_DIR / "data" / "index_universe.csv"
DART_MAJOR_KEYWORDS_FILE = BASE_DIR / "dart" / "major_keywords.txt"
DART_SENT_LOG = BASE_DIR / "data" / "dart_sent_ids.json"

TEMPLATE_PATH = BASE_DIR / "report" / "template.docx"

OUTPUT_DIR = BASE_DIR / "output"
CHART_TMP_DIR = OUTPUT_DIR / ".charts_tmp"

# 기술적 지표 파라미터 (원본 n8n 시트 수식의 정확한 값은 확인 불가 → 업계 표준값 채택)
STOCK_HISTORY_RANGE = "3y"
RSI_LENGTH = 14
STOCH_RSI_LENGTH = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_LENGTH = 20
BB_STD = 2
MA_PERIODS = (5, 20, 60, 120)
VOLUME_AVG_PERIOD = 20
TECH_CHART_LOOKBACK_DAYS = 60  # 원본 프롬프트가 "최근 60거래일" 지표를 근거로 분석