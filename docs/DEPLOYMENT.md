# 서버 배포 (Oracle Cloud)

생성기는 백엔드와 같은 Oracle 서버(`caifr-oracle`, Ubuntu ARM)에서 Docker로 하루 한 번 돈다.
한국거래소 개장일 아침 9시(KST)에 리포트를 만들어 텔레그램으로 보내고, 사이트(`api.caifr.com/api/generator/reports`)에 PDF·한 장 요약 카드와 함께 올린다.
휴장일이면 `run_auto.py`가 아무것도 하지 않고 끝난다.

## 흐름

1. 네이버 경제면 헤드라인 → 오늘의 시황 → 관련 기업 3개 분석 (OpenAI)
2. 한 장 요약 카드(PNG), HTML 템플릿(`report/html/`)을 Chromium으로 인쇄해 PDF 생성
3. 팀 텔레그램 채널로 카드+PDF 전송
4. 백엔드 업로드 (`report/api_upload.py`). 같은 날짜를 다시 올리면 덮어쓰고, 관리자가 붙인 숏츠 주소는 유지된다
5. 어느 단계든 실패하거나 10분을 넘기면 비공개 채널로 실패 알림
6. 숏츠 (`shorts_pipeline/`, 옛 auto-n8n): 올린 PDF로 9:16 영상을 만들어 유튜브에 올리고, 숏츠 주소를 붙여 리포트를 같은 날짜로 다시 올린다
   - 요약·대본 OpenAI, 목소리 Typecast, 장면 영상 Higgsfield, 자막·배속 ffmpeg
   - 리포트와 따로 최대 60분. 실패·시간초과여도 리포트는 그대로 두고 비공개 채널로 알린다
   - `TYPECAST_API_KEY`가 없으면 숏츠만 건너뛴다. 결과는 실행 기록 `stats.shorts`(uploaded·failed 등)에 남는다
   - 영상과 단계별 기록은 `output/shorts/`(`runs/<시각>/run.log`)에 남는다

## 글꼴

PDF는 `report/html/fonts/`에 함께 둔 Pretendard(SIL OFL, `OFL.txt`)만 쓴다. 서버에 설치된 글꼴에 기대지 않아 PC와 서버에서 같은 모양이 나온다.
PDF 모양(표지·2단 본문·차트 배치·쪽 나누기)은 `report/html/template.html`과 `report.css`에서 고친다.
요약 카드는 서버에서 나눔바른고딕(`fonts-nanum`)으로 그린다 (`analysis/summary_card.py`).

## 환경 변수 (`~/report_generator/.env`, 권한 600)

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | O | 분석·글쓰기 |
| `OPENDART_API_KEY` | O | 기업 목록·공시 |
| `REPORT_API_TOKEN` | O | 백엔드 `deploy/.env.app`의 `REPORT_GENERATOR_TOKEN`과 같은 값 |
| `REPORT_API_URL` | | 기본값 `https://api.caifr.com/api/generator/reports`. 실행 기록은 같은 서버의 `.../api/generator/runs`로 보낸다 (주소·토큰이 없으면 기록만 건너뛴다) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DOCX_CHAT_ID` | O | 비공개 채널 (시작·실패 알림). 이름은 예전 docx 채널 그대로. 없으면 실패해도 알림이 오지 않는다 |
| `TELEGRAM_CHAT_ID` | | 팀 채널 (카드+PDF). 설정했는데 전송에 실패하면 실패 알림 |
| `TYPECAST_API_KEY`, `HIGGSFIELD_API_KEY`, `HIGGSFIELD_API_SECRET` | | 숏츠 목소리·장면 영상. `TYPECAST_API_KEY`가 없으면 숏츠를 건너뛴다 |
| `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | | 숏츠 업로드 (`youtube.upload` 범위 refresh token, OAuth Playground로 발급) |
| `YOUTUBE_PRIVACY_STATUS` | | 비우면 공개 + 구독자 알림. `private`로 먼저 확인한다 |
| `YOUTUBE_UPLOAD` | | `false`면 영상만 만들고 올리지 않는다 |

배포 뒤 아래로 이름만 확인한다 (값은 출력하지 않는다).

```bash
ssh caifr-oracle 'cut -d= -f1 ~/report_generator/.env'
```

## 배포

저장소가 비공개라 서버에서 clone하지 않고 로컬에서 보낸다.

```bash
git archive origin/main | ssh caifr-oracle 'mkdir -p ~/report_generator && tar -x -C ~/report_generator'
ssh caifr-oracle 'cd ~/report_generator && mkdir -p output logs && docker build -t caifr-report-generator .'
```

## 자동 실행 (cron, 서버 시간은 UTC)

`crontab -e`에 한 줄. `0 0 * * 1-5` UTC = 평일 09:00 KST.

```cron
0 0 * * 1-5 docker run --rm --name caifr-report-generator --cpus 1 --memory 1g --env-file /home/ubuntu/report_generator/.env -v /home/ubuntu/report_generator/output:/app/output caifr-report-generator >> /home/ubuntu/report_generator/logs/auto.log 2>&1
```

수동 실행은 같은 `docker run` 명령을 그대로 돌리면 된다 (휴장일에는 건너뛴다).

## DART 공시 알림 (`dart_monitor.py`)

같은 이미지로 개장일 08~19시(KST)에 30분마다 돈다. 관심 종목(코스피200·코스닥150)의 주요 공시만 팀 텔레그램 채널(`TELEGRAM_CHAT_ID`)로 보낸다.
이미 보낸 공시 기록은 컨테이너가 지워져도 남도록 서버 폴더 `~/report_generator/state`를 `/app/state`로 연결하고 `DART_SENT_LOG=/app/state/dart_sent_ids.json`으로 가리킨다. 알림마다 임시 파일에 쓰고 바꿔 끼우므로(파일 하나만 연결하면 바꿔 끼울 수 없다) 폴더를 연결한다. 처음 한 번 만든다.

```bash
ssh caifr-oracle 'mkdir -p ~/report_generator/state && cp -n ~/report_generator/data/dart_sent_ids.json ~/report_generator/state/'
```

cron (UTC). 일요일 23시 UTC가 월요일 08시 KST라 두 줄로 나눈다. 휴장일·시간 확인은 스크립트가 한 번 더 한다.

```cron
*/30 23 * * 0-4 docker run --rm --name caifr-dart-monitor --cpus 0.5 --memory 512m --env-file /home/ubuntu/report_generator/.env -v /home/ubuntu/report_generator/state:/app/state -e DART_SENT_LOG=/app/state/dart_sent_ids.json caifr-report-generator python dart_monitor.py >> /home/ubuntu/report_generator/logs/dart.log 2>&1
*/30 0-10 * * 1-5 docker run --rm --name caifr-dart-monitor --cpus 0.5 --memory 512m --env-file /home/ubuntu/report_generator/.env -v /home/ubuntu/report_generator/state:/app/state -e DART_SENT_LOG=/app/state/dart_sent_ids.json caifr-report-generator python dart_monitor.py >> /home/ubuntu/report_generator/logs/dart.log 2>&1
```

## 숏츠 테스트

외부 API는 가짜로 바꾸고 실제 ffmpeg로 렌더링까지 확인한다 (`tests/shorts/`는 auto-n8n에서 옮긴 n8n 동등성 테스트).

```bash
docker build -t caifr-report-generator .
docker run --rm -e OPENAI_API_KEY=x -e OPENDART_API_KEY=x -e TEST_FONTS_DIR=/app/report/html/fonts caifr-report-generator \
  sh -c 'pip install -q --user pytest && python -m pytest -q tests'
```
