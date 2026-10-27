"""The optional deploy job holds a secret, so its shell script is RUN here, not just read.

The exact text of the `run:` block is pulled out of .github/workflows/ci.yml and executed with
bash against a fake Render deploy-hook server on localhost. That proves what the script sends
(method, the image as a properly encoded imgURL, the original ?key= kept), what it refuses, how
it reacts to each status Render can return, and that the secret never appears in its output.
Skipped where bash or curl is missing.
"""

import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
SCRIPT = WF["jobs"]["deploy"]["steps"][0]["run"]
def find_bash():
    """A real bash. On Windows `bash` on PATH is usually WSL's launcher (system32\\bash.exe), which
    does not pass environment variables through and mangles the script's quoting, so prefer Git Bash."""
    if os.name == "nt":
        for candidate in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if Path(candidate).exists():
                return candidate
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash")


BASH, CURL = find_bash(), shutil.which("curl")
pytestmark = pytest.mark.skipif(not (BASH and CURL), reason="a real bash and curl are required")

DIGEST = "ghcr.io/iftakhar005/thikana-api@sha256:" + "ab12" * 16
SECRET_KEY = "s3cr3t-hook-key-DO-NOT-LEAK"


class FakeRender(BaseHTTPRequestHandler):
    seen: list = []
    reply = 200

    def _handle(self):
        parts = urlsplit(self.path)
        FakeRender.seen.append({"method": self.command, "path": parts.path, "query": parse_qs(parts.query)})
        self.send_response(FakeRender.reply)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST = _handle

    def log_message(self, *args):
        pass


@pytest.fixture
def render():
    FakeRender.seen, FakeRender.reply = [], 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeRender)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/deploy/srv-abc123?key={SECRET_KEY}"
    server.shutdown()


def run(tmp_path, hook, image_ref=DIGEST):
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {**os.environ, "RENDER_DEPLOY_HOOK": hook, "IMAGE_REF": image_ref, "GITHUB_STEP_SUMMARY": str(summary)}
    done = subprocess.run([BASH, "-e", "-c", SCRIPT], env=env, capture_output=True, text=True, timeout=60)
    return done, summary.read_text()


def test_it_posts_the_digest_as_an_encoded_imgurl_and_keeps_the_hooks_own_key(render, tmp_path):
    done, summary = run(tmp_path, render)
    assert done.returncode == 0, done.stdout + done.stderr
    (request,) = FakeRender.seen
    assert request["method"] == "POST" and request["path"] == "/deploy/srv-abc123"
    assert request["query"]["key"] == [SECRET_KEY]                    # the hook's own credential survives
    assert request["query"]["imgURL"] == [DIGEST]                     # and the image arrives intact, decoded
    assert "HTTP 200" in done.stdout and DIGEST in summary


def test_a_queued_deploy_is_accepted_too(render, tmp_path):
    FakeRender.reply = 202                                           # another deploy is running: Render queues this one
    done, _ = run(tmp_path, render)
    assert done.returncode == 0 and "HTTP 202" in done.stdout


@pytest.mark.parametrize("status", [401, 404, 500, 503])
def test_any_other_answer_fails_the_job_so_a_failed_deploy_is_never_silent(render, tmp_path, status):
    FakeRender.reply = status
    done, summary = run(tmp_path, render)
    assert done.returncode != 0
    assert f"HTTP {status}" in done.stdout and "nothing was deployed" in done.stdout
    assert summary == ""                                              # no false "asked Render to deploy" note


@pytest.mark.parametrize("bad", [
    "ghcr.io/iftakhar005/thikana-api:latest",                        # a movable tag
    "ghcr.io/iftakhar005/thikana-api:" + "a" * 40,                    # even a commit tag: only digests
    "docker.io/evil/image@sha256:" + "a" * 64,                       # another registry
    "ghcr.io/iftakhar005/thikana-api@sha256:abc",                     # truncated digest
    "ghcr.io/iftakhar005/thikana-api@sha256:" + "a" * 64 + "&x=1",    # parameter smuggling
    "",                                                              # the publish step was skipped
])
def test_it_refuses_to_deploy_anything_that_is_not_a_ghcr_digest_and_never_calls_render(render, tmp_path, bad):
    done, _ = run(tmp_path, render, bad)
    assert done.returncode != 0 and "refusing" in done.stdout
    assert FakeRender.seen == []


def test_an_empty_secret_stops_with_a_clear_message_and_calls_nothing(tmp_path):
    done, _ = run(tmp_path, "")
    assert done.returncode != 0 and "RENDER_DEPLOY_HOOK secret is empty" in done.stdout


def test_the_hook_url_and_key_never_appear_in_anything_the_job_prints_or_writes(render, tmp_path):
    for reply in (200, 401):
        FakeRender.reply = reply
        done, summary = run(tmp_path, render)
        everything = done.stdout + done.stderr + summary
        assert SECRET_KEY not in everything and "srv-abc123" not in everything, reply


def test_the_hook_works_the_same_when_it_has_no_query_string_yet(render, tmp_path):
    hook = render.split("?")[0]
    done, _ = run(tmp_path, hook)
    assert done.returncode == 0
    assert FakeRender.seen[0]["query"] == {"imgURL": [DIGEST]}
