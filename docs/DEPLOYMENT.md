# 서버 배포 (Oracle Cloud)

생성기는 백엔드와 같은 Oracle 서버(`caifr-oracle`, Ubuntu ARM)에서 Docker로 하루 한 번 돈다.
한국거래소 개장일 아침 9시(KST)에 리포트를 만들어 텔레그램으로 보내고, 사이트(`api.caifr.com/api/generator/reports`)에 PDF·한 장 요약 카드와 함께 올린다.
휴장일이면 `run_auto.py`가 아무것도 하지 않고 끝난다.

## 흐름

1. 네이버 경제면 헤드라인 → 오늘의 시황 → 관련 기업 3개 분석 (OpenAI)
2. `report/template.docx`를 채워 docx 생성 → 비공개 텔레그램 채널로 원본 전송
3. 한 장 요약 카드(PNG), LibreOffice로 PDF 변환
4. 팀 텔레그램 채널로 카드+PDF 전송
5. 백엔드 업로드 (`report/api_upload.py`). 같은 날짜를 다시 올리면 덮어쓰고, 관리자가 붙인 숏츠 주소는 유지된다
6. 어느 단계든 실패하거나 10분을 넘기면 비공개 채널로 실패 알림

## 글꼴

템플릿은 `나눔바른고딕`과 `맑은 고딕`을 쓴다. 이미지에 `fonts-nanum`을 넣고, 윈도우 전용인 맑은 고딕은 `docker/fonts.conf`에서 나눔바른고딕으로 대신한다.
요약 카드도 서버에서는 나눔바른고딕으로 그린다 (`analysis/summary_card.py`).

## 환경 변수 (`~/report_generator/.env`, 권한 600)

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | O | 분석·글쓰기 |
| `OPENDART_API_KEY` | O | 기업 목록·공시 |
| `REPORT_API_TOKEN` | O | 백엔드 `deploy/.env.app`의 `REPORT_GENERATOR_TOKEN`과 같은 값 |
| `REPORT_API_URL` | | 기본값 `https://api.caifr.com/api/generator/reports` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DOCX_CHAT_ID` | O | 비공개 채널 (docx 원본, 시작·실패 알림). 없으면 실패해도 알림이 오지 않는다 |
| `TELEGRAM_CHAT_ID` | | 팀 채널 (카드+PDF). 설정했는데 전송에 실패하면 실패 알림 |

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
0 0 * * 1-5 docker run --rm --name caifr-report-generator --env-file /home/ubuntu/report_generator/.env -v /home/ubuntu/report_generator/output:/app/output caifr-report-generator >> /home/ubuntu/report_generator/logs/auto.log 2>&1
```

수동 실행은 같은 `docker run` 명령을 그대로 돌리면 된다 (휴장일에는 건너뛴다).
