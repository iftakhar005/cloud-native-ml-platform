"""The page's JavaScript, tested with Node, and checked against REAL API output.

The unit tests are in tests/js/render.test.cjs. The cross-check below feeds Node what the
real service returned for a text with an emoji in it: the API counts characters the way Python
does (code points), a JavaScript string counts UTF-16 units, and a page that slices the string
directly highlights the wrong words. Skipped when Node is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thikana.api.main import create_app
from thikana.api.settings import Settings
from thikana.training.synth import build_places, generate, split_places
from thikana.training.train import build_vocab, train_model

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")


def test_the_javascript_unit_tests_pass():
    # The file, not the directory: crosscheck.cjs in the same folder is a helper that reads stdin.
    run = subprocess.run([NODE, "--test", str(ROOT / "tests" / "js" / "render.test.cjs")], capture_output=True,
                         text=True, timeout=120, cwd=ROOT)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "# fail 0" in run.stdout and "# pass" in run.stdout


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    places = split_places(build_places())["train"]
    path = tmp_path_factory.mktemp("web-model") / "tiny.crfsuite"
    train_model(generate(places, 400, seed=1), path, {"district": build_vocab(places)["district"]}, memory=True)
    with TestClient(create_app(Settings(model_path=path))) as c:
        yield c


@pytest.mark.parametrize("text", [
    "House 12, Road 5, Mirpur-10, Dhaka-1216",
    "\U0001F3E0 House 12, Road 5, Mirpur-10, Dhaka-1216",                       # one emoji: UTF-16 length differs
    "\U0001F3E0\U0001F3E0\U0001F3E0 Flat 4B, House 7, Block C, Road 3, Banani, Dhaka 1213",
    "বাসা ১২, রোড ৫, ঢাকা-১২০৫",
])
def test_the_page_highlights_exactly_what_the_real_api_found(client, text):
    body = client.post("/api/v1/parse", json={"text": text}).json()
    assert body["entities"], "the model should find something in this address"
    run = subprocess.run([NODE, str(ROOT / "tests" / "js" / "crosscheck.cjs")],
                         input=json.dumps({"text": text, "entities": body["entities"]}),
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    shown = json.loads(run.stdout)
    assert shown["joined"] == text                                                # nothing lost or invented
    assert [s["text"] for s in shown["labelled"]] == [e["text"] for e in body["entities"]]
    assert [s["label"] for s in shown["labelled"]] == [e["label"] for e in body["entities"]]
