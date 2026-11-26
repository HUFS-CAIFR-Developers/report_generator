import json
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def workflow():
    return json.loads((FIXTURES / "n8n_workflow.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def node(workflow):
    nodes = {n["name"]: n for n in workflow["nodes"]}

    def get(name):
        return nodes[name]

    return get


@pytest.fixture(scope="session")
def js_cases():
    return json.loads((FIXTURES / "js_cases.json").read_text(encoding="utf-8"))


requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe 없음")
