"""n8n Code 노드(JS)를 node 로 실제 실행해 만든 기대값(fixtures/js_cases.json)과 Python 포팅 결과를 비교."""
import pytest

from shorts_pipeline.subtitles import SubtitleError, build_srt, to_srt_time


def test_srt_identical_to_js(js_cases):
    cases = js_cases["srt_cases"]
    assert len(cases) == 60
    for i, case in enumerate(cases):
        got = build_srt(case["items"])
        exp = case["expected"]
        assert got["srt"] == exp["srt"], f"case {i}"
        assert got["subtitle_count"] == exp["subtitle_count"], f"case {i}"
        assert got["total_duration"] == pytest.approx(exp["total_duration"], abs=0), f"case {i}"


def test_srt_errors_identical_to_js(js_cases):
    for case in js_cases["srt_errors"]:
        with pytest.raises(SubtitleError) as ei:
            build_srt(case["items"])
        assert str(ei.value) == case["error"]


@pytest.mark.parametrize("sec,expected", [(0, "00:00:00,000"), (0.0005, "00:00:00,001"), (3661.2345, "01:01:01,235"),
                                          (-1, "00:00:00,000"), (59.9996, "00:01:00,000")])
def test_srt_time(sec, expected):
    assert to_srt_time(sec) == expected


def test_parse_final_durations_matches_js(js_cases):
    """Parse Final Scene Durations: 'n|duration' 줄 → (scene_number, final_scene_duration)"""
    data = js_cases["parse_durations"]
    parsed = []
    for line in [x.strip() for x in data["stdout"].strip().split("\n") if x.strip()]:
        scene, dur = line.split("|")
        parsed.append({"scene_number": int(scene), "final_scene_duration": float(dur)})
    assert parsed == data["parsed"]
