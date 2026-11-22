# Oracle 서버(ARM)에서 하루 한 번 도는 리포트 생성기 + 쇼츠 영상 생성. PDF는 LibreOffice, 영상은 ffmpeg로 만든다
# 쇼츠 쪽은 기존 n8n-ffmpeg 이미지와 같은 정적 ffmpeg 6.0을 쓴다 (amd64/arm64 모두 제공)
ARG FFMPEG_IMAGE=mwader/static-ffmpeg:6.0
FROM ${FFMPEG_IMAGE} AS ffmpeg-source

FROM python:3.12-slim-bookworm
COPY --from=ffmpeg-source /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-source /ffprobe /usr/local/bin/ffprobe

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer-nogui fonts-nanum fonts-nanum-extra fontconfig tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY docker/fonts.conf /etc/fonts/local.conf
RUN fc-cache -f

# 리포트 날짜·개장일 판단이 datetime.now() 기준이라 한국 시간으로 둔다
ENV TZ=Asia/Seoul PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# root가 아닌 사용자로 돈다. uid는 서버 ubuntu 사용자(1001)와 맞춰 output/ 마운트에 바로 쓴다
RUN useradd -u 1001 -m app && chown -R app /app
USER app

# 결과물(output/)은 서버에 남기되 30일 지난 것은 지운다
CMD ["sh", "-c", "find output -type f -mtime +30 -delete 2>/dev/null; exec python run_auto.py"]
