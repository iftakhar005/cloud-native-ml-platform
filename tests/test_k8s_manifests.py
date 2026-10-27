"""Static checks on the Kubernetes manifests in k8s/.

A manifest degrades silently: someone sets `readOnlyRootFilesystem: false` to get past an
error, or swaps the image tag for `latest`, and the pod still runs. These read the files
and enforce what docs/kubernetes.md promises. They do not need a cluster; the cluster
itself (Pod Security Admission, probes, rollouts) was exercised for real, see the doc.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from thikana.api.main import create_app
from thikana.api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "k8s" / "base"
LOCAL = ROOT / "k8s" / "overlays" / "local"
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


DEPLOYMENT = load(BASE / "deployment.yaml")
POD = DEPLOYMENT["spec"]["template"]["spec"]
CONTAINER = POD["containers"][0]
SERVICE = load(BASE / "service.yaml")
NAMESPACE = load(BASE / "namespace.yaml")
PDB = load(BASE / "pdb.yaml")
LB = load(LOCAL / "service-lb.yaml")
BASE_KUSTOMIZATION = load(BASE / "kustomization.yaml")
LOCAL_KUSTOMIZATION = load(LOCAL / "kustomization.yaml")


def test_it_runs_as_the_same_non_root_user_the_image_creates():
    uid = int(re.search(r"^USER (\d+):", DOCKERFILE, re.M).group(1))
    sc = POD["securityContext"]
    assert sc["runAsNonRoot"] is True and sc["runAsUser"] == uid and sc["runAsGroup"] == uid
    assert sc["seccompProfile"] == {"type": "RuntimeDefault"}


def test_the_container_is_locked_down():
    sc = CONTAINER["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False
    assert sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"] == {"drop": ["ALL"]}
    assert not sc.get("privileged")
    for forbidden in ("hostNetwork", "hostPID", "hostIPC"):
        assert not POD.get(forbidden)
    assert not any("hostPath" in v for v in POD.get("volumes", []))


def test_the_pod_gets_no_kubernetes_api_credentials():
    assert POD["automountServiceAccountToken"] is False
    assert load(BASE / "serviceaccount.yaml")["automountServiceAccountToken"] is False


def test_the_namespace_makes_the_cluster_enforce_the_restricted_profile():
    labels = NAMESPACE["metadata"]["labels"]
    assert labels["pod-security.kubernetes.io/enforce"] == "restricted"
    assert labels["pod-security.kubernetes.io/warn"] == "restricted"


def test_there_are_several_replicas_and_an_update_never_drops_capacity():
    assert DEPLOYMENT["spec"]["replicas"] >= 2
    strategy = DEPLOYMENT["spec"]["strategy"]
    assert strategy["type"] == "RollingUpdate"
    assert strategy["rollingUpdate"]["maxUnavailable"] == 0
    assert strategy["rollingUpdate"]["maxSurge"] >= 1


def test_requests_and_limits_are_set_and_the_limit_is_not_below_the_request():
    def mem(s):
        return int(re.fullmatch(r"(\d+)Mi", s).group(1))
    r = CONTAINER["resources"]
    assert {"cpu", "memory"} <= set(r["requests"]) and {"cpu", "memory"} <= set(r["limits"])
    assert mem(r["limits"]["memory"]) >= mem(r["requests"]["memory"])


def test_the_three_probes_ask_the_three_different_questions():
    ready = CONTAINER["readinessProbe"]["httpGet"]["path"]
    live = CONTAINER["livenessProbe"]["httpGet"]["path"]
    startup = CONTAINER["startupProbe"]["httpGet"]["path"]
    assert (startup, ready, live) == ("/readyz", "/readyz", "/healthz")
    # liveness must not depend on the model: a restart cannot fix a missing model
    assert live != ready
    served = {route.path for route in create_app(Settings()).routes}
    assert {ready, live} <= served                       # the probes call routes that exist
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert CONTAINER[probe]["httpGet"]["port"] == "http"


def test_the_container_port_is_the_one_the_image_listens_on_and_the_service_reaches_it():
    exposed = int(re.search(r"^EXPOSE (\d+)", DOCKERFILE, re.M).group(1))
    port = CONTAINER["ports"][0]
    assert port["name"] == "http" and port["containerPort"] == exposed
    for service in (SERVICE, LB):
        assert service["spec"]["ports"][0]["targetPort"] == "http"


def test_the_replica_names_itself_from_the_pod_name():
    env = {e["name"]: e for e in CONTAINER["env"]}
    assert env["THIKANA_INSTANCE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.name"


def test_one_set_of_labels_ties_deployment_service_and_budget_together():
    selector = DEPLOYMENT["spec"]["selector"]["matchLabels"]
    template_labels = DEPLOYMENT["spec"]["template"]["metadata"]["labels"]
    assert selector.items() <= template_labels.items()
    for obj in (SERVICE, LB):
        assert obj["spec"]["selector"] == selector
    assert PDB["spec"]["selector"]["matchLabels"] == selector


def test_the_image_is_pinned_to_a_commit_tag_never_latest():
    assert ":" not in CONTAINER["image"]                 # the base names no tag; the overlay sets it
    images = LOCAL_KUSTOMIZATION["images"]
    assert len(images) == 1 and images[0]["name"] == CONTAINER["image"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", str(images[0]["newTag"]))
    assert CONTAINER["imagePullPolicy"] == "IfNotPresent"   # `Always` would defeat a local image


GHCR = ROOT / "k8s" / "overlays" / "ghcr"
GHCR_KUSTOMIZATION = load(GHCR / "kustomization.yaml")


def test_no_secret_is_referenced_or_pasted_into_the_manifests():
    # Every file under k8s/, whatever its name: a credential must never be committed here.
    files = [p for p in (ROOT / "k8s").rglob("*") if p.is_file()]
    assert files
    text = "".join(p.read_text(encoding="utf-8") for p in files)
    assert "kind: Secret" not in text                   # no Secret object, ever, in git
    # Referencing a Secret BY NAME is fine (the Secret is created by hand); the only one is
    # Grafana's admin password. Anything else appearing here is a new decision to review.
    referenced = re.findall(r"secretKeyRef:\s*\n\s*name:\s*(\S+)", text)
    assert referenced == ["grafana-admin"]
    assert "secretGenerator" not in text                # kustomize could generate one from a file
    assert ".dockerconfigjson" not in text and '"auths"' not in text
    assert not re.search(r"ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_|-----BEGIN [A-Z ]*PRIVATE KEY",
                         text)


def test_the_published_image_is_pinned_by_digest_and_pulled_with_a_named_secret_that_is_not_in_git():
    image = GHCR_KUSTOMIZATION["images"][0]
    assert image["name"] == CONTAINER["image"]
    assert image["newName"].startswith("ghcr.io/") and image["newName"].endswith("/thikana-api")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image["digest"])      # bytes, not a movable tag
    assert "newTag" not in image
    patch = yaml.safe_load(GHCR_KUSTOMIZATION["patches"][0]["patch"])
    assert patch == [{"op": "add", "path": "/imagePullSecrets", "value": [{"name": "ghcr-pull"}]}]
    assert GHCR_KUSTOMIZATION["patches"][0]["target"] == {"kind": "ServiceAccount", "name": "thikana"}
    assert "../local" in GHCR_KUSTOMIZATION["resources"]


def test_a_shutdown_has_time_to_finish_after_the_pre_stop_wait():
    wait = CONTAINER["lifecycle"]["preStop"]["sleep"]["seconds"]
    assert wait >= 1 and POD["terminationGracePeriodSeconds"] >= wait + 10


def test_the_overlay_sets_the_namespace_itself():
    # The base's namespace does not reach resources an overlay adds: service-lb.yaml landed
    # in `default` with no pods behind it (found by applying it).
    assert LOCAL_KUSTOMIZATION["namespace"] == BASE_KUSTOMIZATION["namespace"] == "thikana"


def test_the_configmap_values_are_valid_settings():
    literals = dict(item.split("=", 1) for item in BASE_KUSTOMIZATION["configMapGenerator"][0]["literals"])
    assert all(k.startswith("THIKANA_") for k in literals)
    Settings.from_env(literals)                          # raises at startup in the pod if any is invalid
    assert "THIKANA_INSTANCE" not in literals            # that one comes from the pod name instead


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_rendered_overlay_puts_every_object_in_the_namespace_and_wires_the_configmap():
    out = subprocess.run(["kubectl", "kustomize", str(LOCAL)], capture_output=True, text=True, check=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    for d in docs:
        if d["kind"] != "Namespace":
            assert d["metadata"]["namespace"] == "thikana", f"{d['kind']} {d['metadata']['name']}"
    config = next(d for d in docs if d["kind"] == "ConfigMap")["metadata"]["name"]
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    ref = deployment["spec"]["template"]["spec"]["containers"][0]["envFrom"][0]["configMapRef"]["name"]
    assert ref == config and re.fullmatch(r"thikana-config-[a-z0-9]+", config)   # hashed: edits roll the pods
    assert deployment["spec"]["template"]["spec"]["containers"][0]["image"].startswith("thikana-api:")


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_the_rendered_ghcr_overlay_runs_the_digest_and_attaches_the_pull_secret():
    out = subprocess.run(["kubectl", "kustomize", str(GHCR)], capture_output=True, text=True, check=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    image = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]["containers"][0]["image"]
    assert re.fullmatch(r"ghcr\.io/[\w.-]+/thikana-api@sha256:[0-9a-f]{64}", image)
    account = next(d for d in docs if d["kind"] == "ServiceAccount")
    assert account["imagePullSecrets"] == [{"name": "ghcr-pull"}]
    assert not any(d["kind"] == "Secret" for d in docs)             # the secret is never rendered
    for d in docs:
        if d["kind"] != "Namespace":
            assert d["metadata"]["namespace"] == "thikana"
