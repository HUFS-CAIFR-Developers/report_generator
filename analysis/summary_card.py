from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

_FONT_PATH = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
_IDX_REGULAR = 0
_IDX_SEMIBOLD = 4
_IDX_BOLD = 6

_W = 720
_BG = (13, 27, 42)
_ACCENT = (94, 168, 255)
_WHITE = (240, 244, 248)
_GRAY = (160, 172, 184)
_DIVIDER = (40, 56, 74)
_PAD = 48


def _font(index: int, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_FONT_PATH, size, index=index)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, current = [], ""
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(draw, text, font, x, y, max_width, fill, line_gap=8) -> int:
    """줄바꿈된 텍스트를 그리고, 다음에 그릴 y좌표를 반환한다."""
    for line in _wrap(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def generate_summary_card(context: dict, out_path: Path) -> Path:
    """리포트 context(main.py의 _build_report에서 만든 dict)를 받아
    텔레그램에 첨부할 세로형 요약 카드 PNG를 생성한다."""
    max_w = _W - _PAD * 2
    _MAX_H = 2400  # 넉넉히 잡고 실제 그려진 높이만큼 마지막에 잘라낸다
    img = Image.new("RGB", (_W, _MAX_H), _BG)
    draw = ImageDraw.Draw(img)

    y = _PAD
    label_font = _font(_IDX_SEMIBOLD, 22)
    draw.text((_PAD, y), f"오늘의 시황 리포트  ·  {context.get('date', '')}", font=label_font, fill=_ACCENT)
    y += label_font.size + 28

    title_font = _font(_IDX_BOLD, 40)
    y = _draw_wrapped(draw, context.get("final_title", context.get("title", "")), title_font, _PAD, y, max_w, _WHITE, line_gap=6)
    y += 24

    draw.line([(_PAD, y), (_W - _PAD, y)], fill=_DIVIDER, width=2)
    y += 32

    tag_font = _font(_IDX_SEMIBOLD, 22)
    headline_font = _font(_IDX_BOLD, 26)
    body_font = _font(_IDX_REGULAR, 22)

    for i in range(1, 4):
        corp_name = context.get(f"company{i}")
        if not corp_name:
            continue
        ticker = context.get(f"company{i}_ticker", "")
        headline = context.get(f"company{i}_summary", "")
        body = context.get(f"company{i}_tec_summary", "")

        draw.text((_PAD, y), f"#{corp_name} #{ticker}", font=tag_font, fill=_ACCENT)
        y += tag_font.size + 14

        y = _draw_wrapped(draw, headline, headline_font, _PAD, y, max_w, _WHITE, line_gap=6)
        y += 6
        y = _draw_wrapped(draw, body, body_font, _PAD, y, max_w, _GRAY, line_gap=6)
        y += 32

    footer_font = _font(_IDX_REGULAR, 18)
    draw.text((_PAD, y), "자동 생성 · News Analyst Report", font=footer_font, fill=_GRAY)
    y += footer_font.size + _PAD

    final_img = img.crop((0, 0, _W, min(y, _MAX_H)))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    final_img.save(out_path)
    return out_path
