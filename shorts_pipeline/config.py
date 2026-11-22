"""환경변수 기반 설정. API 인증정보는 코드/워크플로우에 두지 않고 .env 또는 OS 환경변수로만 받는다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv 는 선택 의존성
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


class ConfigError(RuntimeError):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass
class Settings:
    # --- 인증정보 (필수) ---
    openai_api_key: str | None = None
    typecast_api_key: str | None = None
    higgsfield_api_key: str | None = None      # "Key <id>:<secret>" 의 <id>
    higgsfield_api_secret: str | None = None   # "Key <id>:<secret>" 의 <secret>
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    youtube_refresh_token: str | None = None

    # --- n8n 노드 파라미터와 동일한 기본값 ---
    openai_model: str = "gpt-5.6-sol"
    typecast_voice_id: str = "tc_68257f68bc6e3c161ab5078d"
    typecast_model: str = "ssfm-v30"
    higgsfield_base_url: str = "https://api.higgsfield.ai"
    poll_interval_sec: float = 5.0        # n8n Wait v1.1 기본값 = 5초
    poll_timeout_sec: float = 1800.0      # n8n 에는 없음: 무한 대기 방지용 상한
    speed_factor: float = 1.5             # "speed up final video"
    timezone: str = "Asia/Seoul"          # Final Filename
    youtube_upload: bool = True           # "Upload a video" (끄려면 --no-upload)
    youtube_category_id: str = ""         # 노드에 미설정 → 기본값 ""
    youtube_privacy_status: str | None = None  # 노드에 미설정 → 보내지 않음

    # --- 경로 ---
    output_dir: Path = field(default_factory=lambda: Path("output"))
    fonts_dir: Path = field(default_factory=lambda: Path("fonts"))
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    keep_temp: bool = False

    @property
    def higgsfield_auth_header(self) -> str:
        return f"Key {self.higgsfield_api_key}:{self.higgsfield_api_secret}"

    @classmethod
    def from_env(cls, env_file: str | os.PathLike | None = ".env") -> "Settings":
        if load_dotenv and env_file and Path(env_file).exists():
            load_dotenv(env_file, override=False)
        s = cls()
        s.openai_api_key = _env("OPENAI_API_KEY")
        s.typecast_api_key = _env("TYPECAST_API_KEY")
        s.higgsfield_api_key = _env("HIGGSFIELD_API_KEY")
        s.higgsfield_api_secret = _env("HIGGSFIELD_API_SECRET")
        s.youtube_client_id = _env("YOUTUBE_CLIENT_ID")
        s.youtube_client_secret = _env("YOUTUBE_CLIENT_SECRET")
        s.youtube_refresh_token = _env("YOUTUBE_REFRESH_TOKEN")
        s.youtube_upload = _env("YOUTUBE_UPLOAD", "true").lower() in ("1", "true", "yes")
        s.youtube_category_id = _env("YOUTUBE_CATEGORY_ID", s.youtube_category_id)
        s.youtube_privacy_status = _env("YOUTUBE_PRIVACY_STATUS")
        s.openai_model = _env("OPENAI_MODEL", s.openai_model)
        s.typecast_voice_id = _env("TYPECAST_VOICE_ID", s.typecast_voice_id)
        s.typecast_model = _env("TYPECAST_MODEL", s.typecast_model)
        s.higgsfield_base_url = _env("HIGGSFIELD_BASE_URL", s.higgsfield_base_url).rstrip("/")
        s.poll_interval_sec = float(_env("POLL_INTERVAL_SEC", str(s.poll_interval_sec)))
        s.poll_timeout_sec = float(_env("POLL_TIMEOUT_SEC", str(s.poll_timeout_sec)))
        s.speed_factor = float(_env("SPEED_FACTOR", str(s.speed_factor)))
        s.timezone = _env("TIMEZONE", s.timezone)
        s.output_dir = Path(_env("OUTPUT_DIR", str(s.output_dir)))
        s.fonts_dir = Path(_env("FONTS_DIR", str(s.fonts_dir)))
        s.ffmpeg_bin = _env("FFMPEG_BIN", s.ffmpeg_bin)
        s.ffprobe_bin = _env("FFPROBE_BIN", s.ffprobe_bin)
        s.keep_temp = _env("KEEP_TEMP", "false").lower() in ("1", "true", "yes")
        return s

    def require_credentials(self) -> None:
        required = [
            ("OPENAI_API_KEY", self.openai_api_key),
            ("TYPECAST_API_KEY", self.typecast_api_key),
            ("HIGGSFIELD_API_KEY", self.higgsfield_api_key),
            ("HIGGSFIELD_API_SECRET", self.higgsfield_api_secret),
        ]
        if self.youtube_upload:
            required += [
                ("YOUTUBE_CLIENT_ID", self.youtube_client_id),
                ("YOUTUBE_CLIENT_SECRET", self.youtube_client_secret),
                ("YOUTUBE_REFRESH_TOKEN", self.youtube_refresh_token),
            ]
        missing = [name for name, value in required if not value]
        if missing:
            hint = " 업로드 없이 영상만 만들려면 --no-upload 를 쓰세요." if self.youtube_upload else ""
            raise ConfigError("필수 환경변수가 없습니다: " + ", ".join(missing) + " (.env.example 참고)." + hint)
