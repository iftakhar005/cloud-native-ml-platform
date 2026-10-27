"""Static checks on .github/workflows/ci.yml.

A pipeline degrades silently: someone "fixes" a red build by loosening a pin, widening
a permission or moving the publish step, and nothing fails. These read the workflow and
enforce what docs/ci.md promises. They cannot run the workflow; actionlint and a local
execution of its shell steps did that (see docs/ci.md for exactly what was and was not
verified).
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
WF = yaml.safe_load(TEXT)
VERIFY, IMAGE = WF["jobs"]["verify"], WF["jobs"]["image"]


def steps(job):
    return job["steps"]


def index_of(job, needle):
    """Index of the first step whose `run` or `uses` contains `needle`."""
    for i, s in enumerate(steps(job)):
        if needle in s.get("run", "") or needle in s.get("uses", ""):
            return i
    raise AssertionError(f"no step containing {needle!r}")


def test_there_are_exactly_the_two_jobs_and_the_image_job_waits_for_verify():
    assert set(WF["jobs"]) == {"verify", "image"}
    assert IMAGE["needs"] == "verify"


def test_triggers_are_safe():
    triggers = WF[True] if True in WF else WF["on"]      # YAML parses a bare `on` as True
    assert "pull_request_target" not in triggers          # runs fork code with a write token
    assert triggers["push"]["branches"] == ["main"]


def test_every_action_is_pinned_to_a_full_commit_sha():
    uses = [s["uses"] for job in WF["jobs"].values() for s in steps(job) if "uses" in s]
    assert uses
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u), f"{u} is not pinned to a commit SHA"
    # the pin must say which release it is, so a human can review it
    for line in TEXT.splitlines():
        if re.search(r"uses: \S+@[0-9a-f]{40}", line):
            assert re.search(r"# v\d+\.\d+\.\d+$", line), f"no version comment: {line.strip()}"


def test_the_trivy_action_is_not_used_and_the_scanner_image_is_pinned_by_digest():
    used = [s["uses"] for job in WF["jobs"].values() for s in steps(job) if "uses" in s]
    assert not any("trivy" in u for u in used)             # action tags were force-pushed in March 2026
    assert re.fullmatch(r"aquasec/trivy:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", WF["env"]["TRIVY_IMAGE"])


def test_default_permissions_are_read_only_and_only_the_image_job_can_write_packages():
    assert WF["permissions"] == {"contents": "read"}
    assert "permissions" not in VERIFY                      # inherits read-only: it runs pip + tests
    assert IMAGE["permissions"] == {"contents": "read", "packages": "write"}


def test_no_secret_is_used_except_the_built_in_token():
    assert set(re.findall(r"secrets\.(\w+)", TEXT)) == {"GITHUB_TOKEN"}


def test_checkouts_do_not_persist_credentials():
    for job in WF["jobs"].values():
        for s in steps(job):
            if s.get("uses", "").startswith("actions/checkout@"):
                assert s["with"]["persist-credentials"] is False


def test_no_github_context_is_interpolated_into_a_shell_script():
    # `${{ ... }}` inside `run:` is how script injection happens; values go through env.
    for job in WF["jobs"].values():
        for s in steps(job):
            assert "${{" not in s.get("run", ""), s.get("name")


def test_verify_job_tests_then_trains_then_gates_then_hands_over_the_gated_files():
    t = index_of(VERIFY, "pytest")
    tr = index_of(VERIFY, "thikana.training.train_all")
    g = index_of(VERIFY, "thikana.training.gate")
    up = index_of(VERIFY, "upload-artifact")
    assert t < tr < g < up
    assert steps(VERIFY)[up]["with"]["if-no-files-found"] == "error"


def test_python_version_matches_the_docker_base_image():
    setup = next(s for s in steps(VERIFY) if s.get("uses", "").startswith("actions/setup-python@"))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"python:{setup['with']['python-version']}-slim" in dockerfile


def test_image_is_tagged_with_the_full_git_sha_and_never_latest():
    assert "${GITHUB_SHA}" in TEXT
    image_line = next(s["run"] for s in steps(IMAGE) if s.get("name") == "Name the image")
    assert ':${GITHUB_SHA}"' in image_line
    assert ":latest" not in TEXT
    build = steps(IMAGE)[index_of(IMAGE, "docker build")]["run"]
    assert 'GIT_SHA="${GITHUB_SHA}"' in build               # what /api/v1/model reports


def test_the_trivy_gate_fails_the_build_on_fixable_high_and_critical_findings():
    gate = next(s["run"] for s in steps(IMAGE) if s.get("name", "").startswith("Trivy gate"))
    for flag in ("--severity HIGH,CRITICAL", "--ignore-unfixed", "--exit-code 1"):
        assert flag in gate
    assert "|| true" not in gate and "continue-on-error" not in str(steps(IMAGE))


def test_publish_is_last_comes_after_every_check_and_only_runs_on_a_push_to_main():
    publish = steps(IMAGE)[-1]
    assert publish["name"] == "Publish to GHCR"
    assert "docker push" in publish["run"]
    assert all("docker push" not in s.get("run", "") for s in steps(IMAGE)[:-1])
    for check in ("docker build", "-d --name smoke", "TRIVY_IMAGE}\" image"):
        assert index_of(IMAGE, check) < len(steps(IMAGE)) - 1
    assert publish["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"


def test_the_token_reaches_only_the_publish_step_and_never_via_the_command_line():
    for s in steps(IMAGE)[:-1]:
        assert "GITHUB_TOKEN" not in str(s)
    publish = steps(IMAGE)[-1]
    assert publish["env"] == {"REGISTRY_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
    assert "--password-stdin" in publish["run"]            # not -p <token>, which lands in process lists


def test_the_smoke_test_runs_the_image_as_kubernetes_will():
    smoke = steps(IMAGE)[index_of(IMAGE, "-d --name smoke")]["run"]
    for flag in ("--read-only", "--cap-drop ALL", "--security-opt no-new-privileges"):
        assert flag in smoke
    assert "git_sha" in smoke and "10001:10001" in smoke


def test_the_image_is_smoke_tested_as_it_will_run_on_the_public_internet():
    step = steps(IMAGE)[index_of(IMAGE, "--name smoke-public")]
    run = step["run"]
    assert "THIKANA_PUBLIC_MODE=true" in run
    for flag in ("--read-only", "--cap-drop ALL", "--security-opt no-new-privileges"):
        assert flag in run
    for hidden in ("/metrics", "/docs", "/openapi.json"):
        assert f'"$(status {hidden})" = "404"' in run              # absent to a stranger
    assert 'status /)" = "200"' in run and "content-security-policy" in run
    assert index_of(IMAGE, "--name smoke-public") < index_of(IMAGE, "docker save")   # before the scan and publish


def test_no_smoke_check_uses_a_bang_which_bash_dash_e_ignores():
    # `! cmd` inside `bash -e` never fails the script, so a "must NOT be present" check written
    # that way would pass even when it should fail.
    for job in WF["jobs"].values():
        for s in steps(job):
            for line in s.get("run", "").splitlines():
                assert not line.strip().startswith("! "), f"{s.get('name')}: {line.strip()}"


@pytest.mark.parametrize("secretish", [r"ghp_[A-Za-z0-9]{20,}", r"github_pat_", r"AKIA[0-9A-Z]{16}",
                                       r"-----BEGIN [A-Z ]*PRIVATE KEY"])
def test_no_credential_is_pasted_into_the_workflow(secretish):
    assert not re.search(secretish, TEXT)
