"""n8n 워크플로우 JSON 원본과 Python 구현이 같은 값/명령을 만드는지 노드 단위로 대조한다."""
import json
import re
from datetime import datetime

import pytest

from shorts_pipeline import llm, media
from shorts_pipeline.config import Settings
from shorts_pipeline.higgsfield import image_payload, video_payload
from shorts_pipeline.pipeline import final_filename, resolve_title
from shorts_pipeline.tts import build_typecast_body
from shorts_pipeline.youtube import upload_payload, youtube_title


def n8n_prompt(node):
    return node["parameters"]["responses"]["values"][0]["content"].lstrip("=")


def n8n_schema(node):
    return json.loads(node["parameters"]["options"]["textFormat"]["textOptions"]["schema"])


def n8n_command(node, **subs):
    """n8n Execute Command 의 쉘 명령에서 표현식을 값으로 치환"""
    cmd = node["parameters"]["command"].lstrip("=")
    for expr, value in subs.items():
        cmd = cmd.replace("{{ " + expr + " }}", str(value))
    return cmd


def quoted_arg(cmd, flag):
    m = re.search(re.escape(flag) + r' \\?\n?"([^"]+)"', cmd)
    assert m, f"{flag} not found"
    return m.group(1)


# ---------------- OpenAI 노드 3개 ----------------
@pytest.mark.parametrize("key,name,expr,value", [
    ("summarize", "보고서 내용 요약정리", "{{ $json.text }}", "REPORT BODY 본문"),
    ("script", "AI 쇼츠대본 생성", "{{ JSON.stringify($json) }}", '{"a":1}'),
])
def test_prompt_text_identical(node, key, name, expr, value):
    expected = n8n_prompt(node(name)).replace(expr, value)
    tmpl = llm.load_prompt(key)
    ph = "report_text" if key == "summarize" else "summary_json"
    assert llm.render(tmpl, **{ph: value}) == expected


def test_visual_prompt_identical(node):
    scene = {"scene_number": 3, "narration": "나레이션", "caption": "캡션", "visual_direction": "연출"}
    expected = n8n_prompt(node("시각화 자료 프롬포트"))
    sk = "$json['output[0].content[0].text.scenes']"
    for field, val in (("scene_number", 3), ("narration", "나레이션"), ("caption", "캡션"), ("visual_direction", "연출")):
        expected = expected.replace("{{ " + sk + "." + field + " }}", str(val))
    expected = expected.replace("{{ $json.audio_duration }}", "4.52")
    scenes = [{"scene_number": 1, "duration": 6.0, "narration": "첫 장면"}, scene]
    stringified = '[{"scene_number":1,"duration":6,"narration":"첫 장면"},' \
                  '{"scene_number":3,"narration":"나레이션","caption":"캡션","visual_direction":"연출"}]'
    expected = expected.replace(
        "{{ JSON.stringify($('AI 쇼츠대본 생성').first().json.output[0].content[0].text.scenes) }}", stringified)
    assert llm.build_visual_prompt(scene, 4.52, scenes) == expected
    assert "{{" not in llm.build_visual_prompt(scene, 4.0, scenes)
    assert "duration: 4\n" in llm.build_visual_prompt(scene, 4.0, scenes)  # JS 숫자 출력과 동일


def test_script_prompt_uses_json_stringify_format():
    out = llm.build_script_prompt({"report_title": "제목", "key_points": ["a", "b"]})
    assert out.rstrip("\n").endswith('{"report_title":"제목","key_points":["a","b"]}')


@pytest.mark.parametrize("key,name", [("summarize", "보고서 내용 요약정리"), ("script", "AI 쇼츠대본 생성"),
                                      ("visual", "시각화 자료 프롬포트")])
def test_schema_and_model_identical(node, key, name):
    assert llm.load_schema(key) == n8n_schema(node(name))
    assert Settings().openai_model == node(name)["parameters"]["modelId"]["value"]


def test_visual_schema_names(node):
    assert llm.SCHEMA_NAMES["script"] == node("AI 쇼츠대본 생성")["parameters"]["options"]["textFormat"]["textOptions"]["name"]
    assert llm.SCHEMA_NAMES["visual"] == node("시각화 자료 프롬포트")["parameters"]["options"]["textFormat"]["textOptions"]["name"]


# ---------------- Typecast ----------------
def test_typecast_params(node):
    p = node("Convert text to speech with timestamps")["parameters"]
    assert p["operation"] == "textToSpeechWithTimestamps" and p["granularity"] == "word"
    body = build_typecast_body("안녕", Settings().typecast_voice_id, Settings().typecast_model)
    assert body == {"voice_id": p["voiceId"]["value"], "text": "안녕", "model": "ssfm-v30",
                    "prompt": {"emotion_type": "smart"}}


# ---------------- Higgsfield ----------------
def test_higgsfield_endpoints(node):
    from shorts_pipeline import higgsfield as hf
    assert node("HF Image Submit")["parameters"]["url"] == Settings().higgsfield_base_url + hf.IMAGE_PATH
    assert node("HF video Submit")["parameters"]["url"] == Settings().higgsfield_base_url + hf.VIDEO_PATH


def test_image_payload_matches_n8n(node):
    body = node("HF Image Submit")["parameters"]["jsonBody"]
    for k, v in {"batch_size": "1", "resolution": '"1080p"', "aspect_ratio": '"9:16"', "enhance_prompt": "false"}.items():
        assert f'"{k}": {v}' in body
    assert set(image_payload("p")) == {"prompt", "batch_size", "resolution", "aspect_ratio", "enhance_prompt"}
    assert image_payload("p") == {"prompt": "p", "batch_size": 1, "resolution": "1080p",
                                  "aspect_ratio": "9:16", "enhance_prompt": False}


@pytest.mark.parametrize("dur,expected", [(0.4, 3), (2.0, 3), (3.01, 4), (7.5, 8), (15, 15), (22.2, 15), ("6.2", 7)])
def test_video_payload_duration_clamp(node, dur, expected):
    body = node("HF video Submit")["parameters"]["jsonBody"]
    assert "Math.max(\n    3,\n    Math.min(\n      15,\n      Math.ceil(Number(" in body
    p = video_payload("v", dur)
    assert p == {"prompt": "v", "sound": "off", "duration": expected, "cfg_scale": 0.5,
                 "multi_shots": False, "aspect_ratio": "9:16"}


def test_status_switch_values(node):
    def outs(name):
        return [r["outputKey"] for r in node(name)["parameters"]["rules"]["values"]]
    from shorts_pipeline import higgsfield as hf
    assert outs("HF Image Status Switch") == ["completed", *hf.PENDING]
    assert outs("HF Video Status Switch") == ["completed", *hf.PENDING]  # 폴백(failed/nsfw/canceled) 출력 삭제됨


def test_wait_interval_default():
    assert Settings().poll_interval_sec == 5.0  # Wait v1.1 기본값 (amount=5, unit=seconds)


# ---------------- ffmpeg 명령 ----------------
SN = "$json.output[0].content[0].text.scene_number"


def test_switch1_passes_only_loop_video(workflow, node):
    rules = node("Switch1")["parameters"]["rules"]["values"]
    assert len(rules) == 1
    cond = rules[0]["conditions"]["conditions"][0]
    assert cond["leftValue"] == "={{ $json.output[0].content[0].text.recommended_asset }}"
    assert cond["rightValue"] == "loop_video"
    assert "fallbackOutput" not in node("Switch1")["parameters"]["options"]
    assert [c["node"] for c in workflow["connections"]["Switch1"]["main"][0]] == ["Read/Write Files from Disk1", "Merge2"]


def test_video_normalize_filter(node):
    cmd = n8n_command(node("Execute Command1"), **{SN: 1})
    assert quoted_arg(cmd, "-vf") == media.VIDEO_NORMALIZE_FILTER
    assert "-c:v libx264" in cmd and "-preset medium" in cmd and "-crf 18" in cmd


def test_scene_final_filter(node):
    cmd = node("Execute Command2")["parameters"]["command"]
    m = re.search(r'-filter_complex \\\n\s+"([^"]+)"', cmd)
    assert m.group(1).replace("${adur}", "4.120000") == media.scene_final_filter("4.120000")
    for frag in ("-c:v libx264", "-preset medium", "-crf 18", "-pix_fmt yuv420p", "-c:a aac", "-b:a 192k", "-ar 48000"):
        assert frag in cmd


def test_subtitle_filter(node):
    cmd = node("Execute Command4")["parameters"]["command"]
    n8n_vf = quoted_arg(cmd, "-vf")
    assert n8n_vf.replace("/home/node/.n8n-files/subtitles.srt", "subtitles.srt") \
                 .replace("/home/node/.n8n-files/fonts", "fonts") == media.subtitles_filter()


def test_speed_filter(node):
    cmd = node("speed up final video")["parameters"]["command"]
    assert quoted_arg(cmd, "-filter_complex") == media.speed_filter(Settings().speed_factor)


def test_cleanup_patterns(node):
    cmd = node("Cleanup Temporary Files")["parameters"]["command"]
    for pat in media.TEMP_PATTERNS:
        assert pat in cmd


# ---------------- 파일명 ----------------
@pytest.mark.parametrize("title,expected", [
    ("미국은 AI 랠리인데, 한국 AI 수혜주는 왜 관망일까?", "20261007_미국은_AI_랠리인데_한국_AI_수혜주는_왜_관망일까.mp4"),
    ("유가 120달러 시대…  반도체·정유주 투자 전략은?", "20261007_유가_120달러_시대_반도체정유주_투자_전략은.mp4"),
    ("  S&P500 +3.5% 급등!  ", "20261007_SP500_35_급등.mp4"),
])
def test_final_filename(node, title, expected):
    expr = node("Final Filename")["parameters"]["assignments"]["assignments"][0]["value"]
    assert ".replace(/[^0-9A-Za-z가-힣 _-]/g, '')" in expr and ".replace(/\\s+/g, '_')" in expr
    assert final_filename(title, datetime(2026, 10, 7, 15, 0)) == expected


@pytest.mark.parametrize("script,summary,expected", [
    ({"video_title": "제목", "scenes": [{"caption": "캡션"}]}, {"report_title": "보고서"}, "제목"),
    ({"video_title": "", "scenes": [{"caption": "캡션"}]}, {"report_title": "보고서"}, "캡션"),
    ({"video_title": "", "scenes": [{"caption": ""}]}, {"report_title": "보고서"}, "보고서"),
    ({"scenes": []}, {"report_title": "보고서"}, "보고서"),
    ({"video_title": "", "scenes": [{}]}, {}, "shorts"),
])
def test_title_fallback_chain(node, script, summary, expected):
    expr = node("Final Filename")["parameters"]["assignments"]["assignments"][0]["value"]
    for frag in ("script?.video_title ||", "script?.scenes?.[0]?.caption ||", "report?.report_title ||", "'shorts'"):
        assert frag in expr
    assert resolve_title(script, summary) == expected


# ---------------- YouTube ----------------
def test_youtube_node_params(workflow, node):
    p = node("Upload a video")["parameters"]
    assert (p["resource"], p["operation"], p["regionCode"]) == ("video", "upload", "KR")
    assert p["options"] == {"notifySubscribers": True}
    assert "categoryId" not in p  # 미설정 → 기본값 ""
    assert upload_payload("t") == {"snippet": {"title": "t", "categoryId": ""}, "status": {}, "recordingDetails": {}}
    assert ".replace(/\\.mp4$/i, '')" in p["title"] and ".replace(/_/g, ' ')" in p["title"]
    assert youtube_title("20261109_AI_랠리_한국.MP4") == "20261109 AI 랠리 한국"
    # 업로드는 파일명 변경 뒤, 임시파일 정리 앞에서 실행된다
    flow = workflow["connections"]
    assert flow["Rename Final Video"]["main"][0][0]["node"] == "Read Final Video"
    assert flow["Read Final Video"]["main"][0][0]["node"] == "Upload a video"
    assert flow["Upload a video"]["main"][0][0]["node"] == "Cleanup Temporary Files"


def test_fallback_branch_removed_and_stray_loop_edge(workflow):
    names = {n["name"] for n in workflow["nodes"]}
    for gone in ("HF Fallback Image Submit", "Wait2", "HF Fallback Image Status", "HF Image Status Switch1",
                 "HF Fallback Image Download", "Merge5", "Edit Fields2"):
        assert gone not in names
    # Switch[1](loop_video) 가 영상 생성과 동시에 Loop Over Items 로 바로 연결됨 → README 8번 참고 (코드에선 옮기지 않음)
    assert "Loop Over Items" in [c["node"] for c in workflow["connections"]["Switch"]["main"][1]]
