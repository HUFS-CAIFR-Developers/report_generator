# 쇼츠 영상 단계 (shorts_pipeline)

리포트 PDF가 만들어지면 이어서 9:16 숏폼 영상(자막, 1.5배속)을 만들어 YouTube에 올립니다.
원래 별도 저장소(`auto-n8n`)에서 사람이 PDF를 직접 넣어 돌리던 코드를 리포트 생성기 안으로 옮겨, 이제 리포트 다음 단계로 자동 실행됩니다.

```
뉴스 → 리포트(docx/PDF) → 텔레그램·사이트 업로드 → report/shorts.py → ShortsPipeline.run() → output/shorts/20261030_제목.mp4 → YouTube
```

> **주의:** n8n 노드에 공개 범위가 지정돼 있지 않아 코드에서도 지정하지 않습니다. 구독자 알림은 켜져 있습니다. 먼저 비공개로 확인하려면 `.env`에 `YOUTUBE_PRIVACY_STATUS=private`를 넣거나 `--no-upload`로 실행하세요.

## 실행

```bash
python run_auto.py                                   # 서버 자동실행: 리포트 → 쇼츠 (개장일만)
python main.py --auto                                # 수동: 오늘의 시황 리포트 → 쇼츠
python main.py --url <기사 URL>                      # 수동: 기사 1건 리포트 → 쇼츠
python main.py --auto --no-shorts                    # 리포트만
python main.py --auto --no-upload                    # 쇼츠 영상까지 만들되 YouTube에는 안 올림
python main.py --shorts-only output/<리포트>.pdf      # 이미 만든 리포트로 쇼츠만 (실패 시 재시도용)
```

`SHORTS_ENABLED=false`면 쇼츠 단계를 통째로 건너뜁니다. 쇼츠 단계는 리포트 사이트 업로드까지 끝난 뒤에 돌기 때문에, 쇼츠가 실패해도 리포트에는 영향이 없습니다.
`run_auto.py`는 리포트(10분 제한)와 쇼츠(`SHORTS_TIMEOUT_SECONDS`, 기본 90분 제한)를 따로 감시하고, 쇼츠 완료·실패를 비공개 텔레그램 채널로 알립니다.

필요한 환경변수는 `.env.example`의 "쇼츠 영상" 항목을 보세요. `OPENAI_API_KEY`는 리포트와 같은 값을 씁니다. ffmpeg/ffprobe가 필요하며 Docker 이미지에는 들어 있습니다.

YouTube 인증값은 n8n에서 꺼낼 수 없어 새로 발급해야 합니다. Google Cloud의 OAuth 클라이언트 ID/시크릿을 준비한 뒤, [OAuth Playground](https://developers.google.com/oauthplayground)에서 "Use your own OAuth credentials"를 켜고 `https://www.googleapis.com/auth/youtube.upload` 범위로 refresh token을 받아 `.env`에 넣으세요.

`python -m shorts_pipeline <파일>` 단독 실행도 그대로 됩니다 (`--text`, `--stdin`, `--no-upload`). 다만 이때는 결과가 `output/`에 바로 쌓이니, 보통은 `main.py --shorts-only`를 쓰세요.

## n8n 노드 ↔ 코드 매핑

| n8n 노드 | 코드 |
|---|---|
| On form submission, Extract from File | `report/shorts.py` → `interface.ReportInput.from_file` (pypdf) |
| 보고서 내용 요약정리 / AI 쇼츠대본 생성 / 시각화 자료 프롬포트 | `llm.py` (프롬프트·스키마는 `prompts/` 에 원문 그대로) |
| Split Out, Merge Scene + Typecast, Loop Over Items | `pipeline.py` 장면 루프 |
| Convert text to speech with timestamps, Read/Write4, Execute Command5 | `tts.py` + `FFmpeg.probe_duration` |
| Switch, HF Image/Video Submit·Wait·Status·Switch·Download | `higgsfield.py` |
| Switch1 (`loop_video`만 통과) | `pipeline.py` 장면 루프 |
| Read/Write Files from Disk1, Execute Command1 | `FFmpeg.normalize_video` |
| Execute Command2 | `FFmpeg.finalize_scene` + `FFmpeg.concat` |
| Measure/Parse Final Scene Durations, Merge SRT Timing, Create SRT from Typecast | `subtitles.build_srt` |
| Execute Command4, speed up final video, Final Filename, Rename, Cleanup | `FFmpeg.burn_subtitles`, `speed_up`, `pipeline.final_filename`, `media.cleanup` |
| Read Final Video, Upload a video | `youtube.py` |

## 실행 로그와 산출물

실행마다 `output/shorts/runs/<리포트 파일명>/` 폴더가 생깁니다 (단독 실행이면 `output/runs/<YYYYmmdd_HHMMSS>/`).
- `run.log`: 단계별 시작/완료/소요시간, 장면별 결과, 오류 스택
- `summary.json`, `script.json`, `tts.json`, `visuals.json`: 중간 결과
- `result.json`(성공 시) / `error.json`(실패 단계·장면)
- `work/`: 임시 미디어. 성공하면 삭제되고, 실패하거나 `--keep-temp`이면 남습니다.

## n8n과 의도적으로 다르게 만든 부분

최종 결과물은 같고, 아래는 안정성 때문에 바꾼 부분입니다.
1. **작업 폴더 분리**: 공용 `/home/node/.n8n-files` 대신 실행마다 별도 폴더를 씁니다(동시 실행 시 파일 충돌 없음).
2. **Execute Command7 생략**: n8n에서도 바로 다음 Command2가 그 결과물을 지우고 다시 만들었기 때문에 결과가 같습니다. Command2는 n8n에서 장면 수만큼 같은 작업을 반복했지만, 여기서는 한 번만 실행합니다.
3. **`image` 장면**: n8n의 Switch1은 `loop_video`만 통과시켜, `recommended_asset=image` 장면은 이미지를 생성한 뒤 영상에서 나레이션과 함께 빠집니다. 여기서도 그 장면을 빼지만, 어차피 버려질 이미지는 생성하지 않아 크레딧을 쓰지 않고 `scenes_skipped`에 남깁니다.
4. **실패 처리**: 영상 생성 실패 시 이미지로 대체하던 브랜치가 워크플로우에서 삭제되어, n8n에서는 영상이 `failed`/`nsfw`/`canceled`로 끝나면 Switch에 출력이 없어 장면이 조용히 빠집니다. 여기서도 그 장면을 빼고 계속 진행하지만, 로그와 `result.json`의 `scenes_skipped`에 남깁니다. 모든 장면이 실패하면 오류로 멈춥니다. 알 수 없는 상태값이 오거나 `POLL_TIMEOUT_SEC`(기본 30분)를 넘기면 오류로 처리합니다. n8n은 무한 대기했습니다.
5. **재시도**: 상태 조회와 다운로드(GET)는 429/5xx 응답에 백오프 재시도합니다. 생성·업로드 요청은 중복을 막기 위해 재시도하지 않습니다. OpenAI SDK 재시도는 3회입니다.
6. **대본 프롬프트 입력**: n8n은 OpenAI 응답 객체 전체(메타데이터 포함)를 `JSON.stringify`로 넘겼습니다. 여기서는 요약 JSON만 같은 형식으로 넘깁니다.
7. **YouTube 업로드 실패**: n8n처럼 오류로 멈추고 임시파일을 남깁니다. 완성된 mp4는 `output/`에 그대로 있습니다.
8. **`Switch[1] → Loop Over Items` 연결은 옮기지 않음**: 워크플로우에 `loop_video` 장면을 영상 생성과 동시에 `Loop Over Items`로 바로 되돌리는 연결이 있습니다. 이렇게 되면 영상 없는 항목이 루프에 먼저 들어가 장면이 중복되거나 `Read/Write Files from Disk1`에서 바이너리 없음 오류가 날 수 있습니다. 폴백 브랜치를 지우면서 남은 연결로 보여서, 코드는 영상 생성이 끝난 항목만 다음 단계로 넘깁니다.

## 테스트

```bash
docker build -f tests/Dockerfile.test -t caifr-report-generator-test .
docker run --rm caifr-report-generator-test
```

- `test_parity_n8n.py`: `tests/fixtures/n8n_workflow.json`(원본에서 API 키만 제거한 사본)을 직접 읽습니다. 프롬프트, 스키마, 모델, 요청 본문, 상태 분기값, ffmpeg 필터 문자열, 파일명 규칙이 원본과 글자 단위로 같은지 비교합니다.
- `test_subtitles_js_parity.py`: n8n Code 노드의 JS를 node로 그대로 실행해 만든 기대값 60건과 오류 3건(`tests/tools/gen_srt_cases.js`)을 Python 결과와 비교합니다.
- `test_higgsfield.py`: 대기→상태→완료, 영상·이미지 실패, 타임아웃 흐름을 확인합니다.
- `test_youtube.py`: 토큰 발급, resumable 업로드 요청, 1MiB 분할 전송, 308 처리, 오류 흐름을 확인합니다.
- `test_e2e_mock.py`: 외부 API만 가짜로 바꾸고 실제 ffmpeg로 5개 장면(영상/이미지 제외/생성 실패 포함)을 끝까지 렌더링합니다. 해상도, 오디오, 길이, 자막, 업로드 순서, 정리 단계를 검증합니다.

실제 OpenAI/Typecast/Higgsfield/YouTube 호출은 테스트에 포함되지 않습니다. 키를 넣은 뒤 짧은 보고서를 `--no-upload`로 먼저 실행해 확인하세요.
