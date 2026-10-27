"""Static checks on the Dockerfile and .dockerignore.

A Dockerfile degrades silently: someone adds `COPY . .` to "fix" a build error and the
size, the security posture and the personal-data guarantee vanish with no failing test.
These read the two files and enforce what docs/docker.md promises. They do not need
Docker installed.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
IGNORE = [line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
          if line.strip() and not line.strip().startswith("#")]


def instructions():
    """Dockerfile instructions with continuation lines joined and comments dropped."""
    joined = re.sub(r"\\\n", " ", DOCKERFILE)
    return [l.strip() for l in joined.splitlines() if l.strip() and not l.strip().startswith("#")]


def allowed():
    return [p[1:] for p in IGNORE if p.startswith("!")]


def test_dockerignore_is_an_allowlist():
    assert IGNORE[0] == "*"                       # everything is out until let in
    forbidden = (".git", ".venv", ".env", "data", "tests", "docs", "reports", "thikana/training")
    for entry in allowed():
        top = entry.rstrip("/")
        assert not any(top == f or top.startswith(f + "/") for f in forbidden), entry


def test_every_allowed_path_exists_except_the_gitignored_model():
    for entry in allowed():
        if entry.startswith("models/"):
            continue  # gitignored: built by `python -m thikana.training.train_all`
        assert (ROOT / entry).exists(), f"{entry} is allowed but does not exist"


def test_every_copy_source_is_permitted_by_the_allowlist():
    for line in instructions():
        if not line.startswith("COPY") or "--from=" in line:
            continue
        parts =[p for p in line.split() if not p.startswith("--")][1:]   # drop COPY and flags
        for source in parts[:-1]:                                          # last item is the destination
            assert any(source == a or source.startswith(a.rstrip("/") + "/") or a.rstrip("/") == source.rstrip("/")
                       for a in allowed()), f"COPY {source} is not in .dockerignore's allowlist"


def test_nothing_copies_the_whole_repository_or_the_training_code():
    for line in instructions():
        if line.startswith("COPY") and "--from=" not in line:
            assert not re.search(r"COPY\s+(--\S+\s+)*\.\s", line), line   # "COPY . ."
            assert "thikana/training" not in line, line
            assert "data/" not in line, line


def test_base_image_is_pinned_by_digest():
    assert re.search(r"^ARG PYTHON_IMAGE=python:3\.12-slim@sha256:[0-9a-f]{64}$", DOCKERFILE, re.M)
    assert len(re.findall(r"^FROM \$\{PYTHON_IMAGE\}", DOCKERFILE, re.M)) == 2   # builder + runtime


def test_the_process_runs_as_a_numeric_non_root_user():
    users = [l for l in instructions() if l.startswith("USER")]
    assert users, "no USER instruction: the container would run as root"
    uid = users[-1].split()[1].split(":")[0]
    assert uid.isdigit() and int(uid) > 0         # numeric, so Kubernetes can verify it is not root


def test_the_runtime_stage_is_multi_stage_and_has_no_build_tools():
    assert "AS builder" in DOCKERFILE and "AS runtime" in DOCKERFILE
    assert "COPY --from=builder" in DOCKERFILE
    runtime = DOCKERFILE.split("AS runtime", 1)[1]
    assert "pip install" not in runtime and "apt-get" not in runtime


def test_wheels_only_so_the_compiler_free_builder_fails_loudly():
    assert "--only-binary=:all:" in DOCKERFILE


def test_cmd_is_exec_form_so_sigterm_reaches_the_server():
    cmd = [l for l in instructions() if l.startswith("CMD")][-1]
    assert cmd.startswith("CMD [") and "uvicorn" in cmd        # a JSON array, not `CMD uvicorn ...`
    assert "--workers" not in cmd                              # scale with replicas, not workers


def test_uvicorns_own_forwarded_header_handling_is_off_so_only_the_apps_limiter_decides():
    cmd = [l for l in instructions() if l.startswith("CMD")][-1]
    assert "--no-proxy-headers" in cmd     # else a forged X-Forwarded-For from localhost rewrites the client address


def test_a_healthcheck_probes_readiness_not_just_liveness():
    check = [l for l in instructions() if l.startswith("HEALTHCHECK")]
    assert check and "/readyz" in check[0]


def test_code_and_model_layers_are_ordered_least_to_most_frequently_changing():
    copies = [l for l in instructions() if l.startswith("COPY") and "--from=" not in l]
    models = next(i for i, l in enumerate(copies) if "models/" in l)
    api = next(i for i, l in enumerate(copies) if "thikana/api/" in l)
    assert models < api                                         # model rarely changes, API code often


def test_no_secrets_are_set_in_the_image():
    for line in instructions():
        if line.startswith(("ENV", "ARG")):
            assert not re.search(r"(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE)", line, re.I), line


@pytest.mark.parametrize("name", ["thikana/api/main.py", "thikana/model.py", "requirements/serve.txt"])
def test_the_files_the_image_depends_on_are_allowed(name):
    assert any(name == a or name.startswith(a.rstrip("/") + "/") for a in allowed())
