"""OpenAI 노드 3개(보고서 요약 → 쇼츠 대본 → 장면별 시각화 프롬프트) 대체.

프롬프트/JSON 스키마는 n8n 워크플로우에서 원문 그대로 추출한 `prompts/*.txt|*.schema.json` 을 쓴다.
n8n 표현식 자리는 `{{name}}` 플레이스홀더로 바꿔 두었다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from .errors import PipelineError
from .logging_setup import get_logger

PROMPT_DIR = Path(__file__).parent / "prompts"
log = get_logger("llm")

# n8n 노드의 textOptions.name (요약 노드는 비어 있어서 이름을 지정)
SCHEMA_NAMES = {"summarize": "report_summary", "script": "Shorts_script", "visual": "visual_prompt"}


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    return json.loads((PROMPT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def render(template: str, **values: Any) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", _to_template_str(value))
    return out


def _to_template_str(value: Any) -> str:
    # n8n `{{ }}` 은 숫자를 JS 문자열 변환 규칙으로 출력한다 (예: 4.0 → "4")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def js_stringify(obj: Any) -> str:
    """JSON.stringify 와 같은 압축 형식 (공백 없음, 유니코드 그대로)."""
    return json.dumps(_js_value(obj), ensure_ascii=False, separators=(",", ":"))


def _js_value(v: Any) -> Any:
    # JS 숫자는 정수/실수 구분이 없어 6.0 도 6 으로 출력된다
    if isinstance(v, dict):
        return {k: _js_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_js_value(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def build_summarize_prompt(report_text: str) -> str:
    return render(load_prompt("summarize"), report_text=report_text)


def build_script_prompt(summary: dict[str, Any]) -> str:
    return render(load_prompt("script"), summary_json=js_stringify(summary))


def build_visual_prompt(scene: dict[str, Any], audio_duration: float, all_scenes: list[dict[str, Any]]) -> str:
    return render(
        load_prompt("visual"),
        scene_number=scene["scene_number"],
        duration=audio_duration,
        narration=scene["narration"],
        caption=scene["caption"],
        visual_direction=scene["visual_direction"],
        all_scenes_json=js_stringify(all_scenes),
    )


class LLMClient(Protocol):
    def structured(self, prompt: str, schema_key: str) -> dict[str, Any]: ...


class OpenAIClient:
    """OpenAI Responses API + strict json_schema (n8n OpenAI 노드 v2.3 과 같은 호출 방식)."""

    # 호출 하나가 멈춰 숏츠 전체 제한(60분)을 다 쓰지 않게 리포트 쪽(config.OPENAI_TIMEOUT_SECONDS=90)과 비슷하게 둔다
    def __init__(self, api_key: str, model: str, max_retries: int = 3, timeout: float = 120.0):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key, max_retries=max_retries, timeout=timeout)

    def structured(self, prompt: str, schema_key: str) -> dict[str, Any]:
        try:
            resp = self._client.responses.create(
                model=self.model,
                input=[{"role": "user", "content": prompt}],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": SCHEMA_NAMES[schema_key],
                        "schema": load_schema(schema_key),
                        "strict": True,
                    }
                },
            )
        except Exception as e:
            raise PipelineError(f"openai:{schema_key}", f"OpenAI 호출 실패: {e}") from e
        raw = getattr(resp, "output_text", None)
        if not raw:
            raise PipelineError(f"openai:{schema_key}", f"응답 본문이 비어 있습니다 (status={getattr(resp, 'status', '?')})")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise PipelineError(f"openai:{schema_key}", f"JSON 파싱 실패: {e}: {raw[:300]}") from e


# ---------- 단계 함수 ----------
def summarize_report(llm: LLMClient, report_text: str) -> dict[str, Any]:
    return llm.structured(build_summarize_prompt(report_text), "summarize")


def generate_script(llm: LLMClient, summary: dict[str, Any]) -> dict[str, Any]:
    script = llm.structured(build_script_prompt(summary), "script")
    scenes = script.get("scenes") or []
    if not scenes:
        raise PipelineError("openai:script", "대본에 scenes 가 없습니다")
    total = sum(float(s.get("duration") or 0) for s in scenes)
    log.info("대본 생성: '%s' / 장면 %d개 / 예상 %.1fs", script.get("video_title"), len(scenes), total)
    return script


def generate_visual_prompt(llm: LLMClient, scene: dict[str, Any], audio_duration: float,
                           all_scenes: list[dict[str, Any]]) -> dict[str, Any]:
    out = llm.structured(build_visual_prompt(scene, audio_duration, all_scenes), "visual")
    if out.get("recommended_asset") not in ("image", "loop_video"):
        raise PipelineError("openai:visual", f"잘못된 recommended_asset: {out.get('recommended_asset')!r}",
                            scene=scene["scene_number"])
    return out
