from pathlib import Path

import requests

import config

_API_BASE = "https://api.telegram.org"


def _post(method: str, data: dict, files: dict | None = None) -> bool:
    url = f"{_API_BASE}/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    resp = requests.post(url, data=data, files=files, timeout=60)
    resp.raise_for_status()
    return True


def send_text(message: str) -> bool:
    """카드/PDF 없이 텍스트만 보낸다 (DART 공시 알림 등). 토큰/챗ID 없거나 실패 시 False."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    try:
        _post("sendMessage", {"chat_id": config.TELEGRAM_CHAT_ID, "text": message})
        return True
    except Exception as e:
        print(f"텔레그램 전송 실패 (건너뜀): {e}")
        return False


def send_report(pdf_path: Path | None, message_text: str, card_path: Path | None = None) -> bool:
    """생성된 리포트를 공개(또는 팀) 채널로 전송한다.
    card_path가 있으면 요약 카드 이미지를 message_text와 함께 먼저 보낸다. pdf_path가 있으면
    PDF도 이어서 보낸다.
    토큰/챗ID가 설정 안 돼있거나 전송이 실패해도 파이프라인은 중단하지 않고 False를 반환한다."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False

    try:
        if card_path and card_path.exists():
            with open(card_path, "rb") as f:
                _post(
                    "sendPhoto",
                    {"chat_id": config.TELEGRAM_CHAT_ID, "caption": message_text[:1024]},
                    {"photo": (card_path.name, f)},
                )
        if pdf_path and pdf_path.exists():
            doc_data = {"chat_id": config.TELEGRAM_CHAT_ID}
            if not card_path:
                doc_data["caption"] = message_text[:1024]
            with open(pdf_path, "rb") as f:
                _post("sendDocument", doc_data, {"document": (pdf_path.name, f)})
        elif not card_path:
            # 카드도 PDF도 없으면 최소한 텍스트라도 보낸다
            _post("sendMessage", {"chat_id": config.TELEGRAM_CHAT_ID, "text": message_text})
        return True
    except Exception as e:
        print(f"텔레그램 전송 실패 (건너뜀): {e}")
        return False


def send_pdf_followup(pdf_path: Path) -> bool:
    """PDF 변환이 카드+텍스트 전송 이후에 뒤늦게 성공했을 때, 그 PDF만 공개 채널에 추가로
    보낸다 (캡션 없음 - 카드+텍스트가 이미 나갔으므로). 토큰/챗ID 미설정이거나 실패해도
    파이프라인은 중단 안 함."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    if not pdf_path or not pdf_path.exists():
        return False
    try:
        with open(pdf_path, "rb") as f:
            _post("sendDocument", {"chat_id": config.TELEGRAM_CHAT_ID}, {"document": (pdf_path.name, f)})
        return True
    except Exception as e:
        print(f"PDF 추가 전송 실패 (건너뜀): {e}")
        return False


def send_text_private(message: str) -> bool:
    """비공개 채널(TELEGRAM_DOCX_CHAT_ID)에 텍스트만 보낸다 (작동 시작 알림, 노트북
    기상 알림 등 상태 알림용). 토큰/채널ID 없거나 실패 시 False."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_DOCX_CHAT_ID:
        return False
    try:
        _post("sendMessage", {"chat_id": config.TELEGRAM_DOCX_CHAT_ID, "text": message})
        return True
    except Exception as e:
        print(f"텔레그램 전송 실패 (건너뜀): {e}")
        return False

