# 새 PC에서 Claude Code에게 붙여넣을 프롬프트

아래 내용을 그대로 복사해서, 새 PC에서 이 프로젝트 폴더를 열어놓은 Claude Code 세션의
첫 메시지로 붙여넣으세요.

---

너는 `/Users/{사용자명}/news-analyst-report/` 프로젝트를 이어서 작업하게 됐어. 이 프로젝트는
뭔지, 뭐가 이미 결정/구현됐는지, 뭘 다시 건드리면 안 되는지 아래에 정리해뒀으니 읽고
시작해줘.

## 프로젝트가 뭔지

n8n으로 만들었던 "뉴스 기사 → 애널리스트 리포트 자동 생성" 워크플로우를 Python으로
재구현한 프로젝트야. 매일 아침(평일) 자동으로:
1. 네이버 경제면 헤드라인 수집 → 오늘의 시황 핵심 이슈 도출 → 시황 브리핑 작성
2. 관련 상장기업 3개 선정 (LLM이 스스로 아는 기업명을 말하면, 로컬 KRX 마스터 DB와
   rapidfuzz로 매칭 — **전체 상장기업 목록을 프롬프트에 주입하지 않음**, 이게 핵심 설계
   원칙이야, 절대 되돌리지 마)
3. 기업별 투자분석 + 기술적분석(RSI/MACD/볼린저밴드 등 직접 계산) + matplotlib 차트
4. Word 템플릿(`report/template.docx`)에 docxtpl로 채워서 `.docx` 생성 → PDF 변환
5. 요약 카드 이미지(PIL로 직접 그림, AI 이미지 생성 아님) 생성
6. 텔레그램 채널에 카드+PDF 전송, 외부 서버(api.caifr.com)에 PDF 업로드

## 핵심 파일 구조

- `main.py` — 파이프라인 본체 (`run()`=수동, `run_auto()`=자동, 공유 로직은 `_build_report()`)
- `run_auto.py` — launchd가 매일 실행하는 진입점, 거래일 체크
- `retry_pdf.py` — PDF 변환 실패 시 20분마다 재시도하는 안전망 (아래 "알려진 이슈" 참고)
- `config.py` — 모든 설정값, `.env`에서 시크릿 로드
- `prompts/*.txt` — 모든 LLM 프롬프트가 여기 텍스트 파일로 분리되어 있음 (사용자가 직접
  편집 가능하게 만든 것). `analysis/prompt_loader.py`가 `<<<PROMPT>>>` 마커로 안내문/본문
  분리해서 읽음
- `analysis/` — company_pick, market_topic, report_writer, summarize, charts, summary_card,
  text_utils
- `report/build_doc.py` — docxtpl 렌더링 + PDF 변환
- `report/telegram_notify.py`, `report/api_upload.py` — 외부 전송

## 절대 다시 시도하면 안 되는 것 (이미 검증 끝남, 실패함)

1. **LibreOffice로 PDF 변환 교체** — 이 방식으로 팝업 문제는 없앨 수 있는데, 한글이
   아예 안 그려지는 렌더링 버그가 있음 (Full Disk Access, 폰트 치환 다 시도해봤는데
   실패). 절대 다시 손대지 마.
2. **PDF 출력 폴더를 `~/Documents`로 옮기기** — 웹에 흔히 나오는 "권장" 방법인데,
   실제로는 더 나쁨: AppleScript 자동화로 Documents에 저장하려고 하면 -1708 에러로
   조용히 실패함. 원래 프로젝트 폴더(`output/`)가 오히려 더 잘 됨. 절대 다시 옮기지 마.
3. **macOS Full Disk Access로 Word 권한 팝업 해결** — Word는 App Sandbox 앱이라
   Full Disk Access와 완전히 다른 층위의 권한 체계를 씀. 효과 없음.

## 알려진 이슈 (해결 안 됐고, 현재 이렇게 대응 중)

- **Word가 새로 생성된 파일마다 "파일 액세스 부여" 팝업을 띄움** (macOS App Sandbox
  특성, Word 쪽 설정으로 우회 불가능함을 확인함). 대응: 사람이 없으면 그날은 팝업 없이
  PDF만 실패하고 나머지(카드+docx 텔레그램 전송)는 정상 진행 → `retry_pdf.py`가 20분마다
  재시도하다가 나중에 사람이 팝업 눌러주면 그때 PDF를 텔레그램에 추가 전송.
- **맥이 절전 상태면 자동실행이 중간에 멈출 수 있음** — `pmset repeat wakeorpoweron`으로
  완화했지만 새 PC에서는 다시 설정해야 함.

## 외부 연동 현재 상태

- **텔레그램**: 정상 작동. 봇 토큰/채널ID는 `.env`의 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`.
- **외부 서버 업로드** (`report/api_upload.py`): `POST {REPORT_API_URL}`에
  `multipart/form-data`로 PDF 파일 자체 + `title`/`report_date`/`category`/`company` 필드
  전송. 서버가 S3에 저장하는 구조. **현재 서버 쪽에서 500 에러 디버깅 중** (nginx
  413은 해결했고, 지금은 백엔드 애플리케이션 에러 — 서버 관리자가 로그 확인 중이었음).
  이건 클라이언트 코드 문제가 아니니 재작업하지 말고, 서버 쪽 상태부터 확인해.

## `.env` 필요한 값

```
OPENAI_API_KEY=
OPENDART_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
REPORT_API_URL=https://api.caifr.com/api/reports
REPORT_API_TOKEN=
```

## 이 프로젝트에서 지켜야 할 작업 방식

- **API 키/토큰을 절대 채팅창에 붙여넣으라고 하지 마** — 항상 `.env` 파일에 직접
  넣으라고 안내해.
- **코드 변경하면 실제로 파이프라인을 돌려서 검증해** — "이론상 되겠지"로 끝내지 말고,
  진짜 리포트 생성해서 lxml 파싱/플레이스홀더 잔존 여부 확인하고, 시각적 확인이 필요하면
  실제 파일을 보내서 확인받아.
- **구현 안 된 걸 구현된 것처럼 얼버무리지 마** — 안 되는 건 안 된다고 바로 말해.
- **n8n 원본 프롬프트와 현재 프롬프트가 충돌하면** (예: 제목 길이, 요약 길이) 조용히
  한쪽을 고르지 말고 뭘 다르게 했는지/왜 다르게 했는지 남겨.

## 새 PC 셋업 체크리스트

1. Python 가상환경: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. Microsoft Word 설치 (PDF 변환용, 정품)
3. `.env` 파일 옮기기 (위 값들)
4. `~/Library/LaunchAgents/com.newsanalystreport.autorun.plist`,
   `com.newsanalystreport.pdfretry.plist` 복사 후 경로 안의 사용자명 확인, `launchctl load`
5. `sudo pmset repeat wakeorpoweron MTWRF 09:15:00`
6. 첫 며칠은 Word 권한 팝업 수동으로 눌러줘야 함 (정상, 새 파일마다 처음 한 번씩)

---

여기까지 읽었으면, 먼저 `output/` 폴더의 최근 리포트 파일 하나 열어보고 실제로 파이프라인이
잘 도는 상태인지 확인한 다음 작업 시작해줘.
