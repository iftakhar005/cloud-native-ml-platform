"""Checks on k8s/monitoring: Prometheus rules, the Grafana dashboard and the manifests.

Monitoring fails quietly: a dashboard panel that queries a metric name that does not
exist shows an empty graph forever, an alert rule with a typo never fires, and nobody
notices until the day it was needed. These tests tie every query to the metrics the
application REALLY exports, run the alert rules against synthetic data with promtool when
Docker is available, and pin the security properties of the monitoring pods.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from thikana.api.main import create_app
from thikana.api.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
MON = ROOT / "k8s" / "monitoring"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


PROM = load(MON / "prometheus" / "prometheus.yml")
ALERTS = load(MON / "prometheus" / "alerts.yml")
DASHBOARD = json.loads((MON / "grafana" / "thikana-dashboard.json").read_text(encoding="utf-8"))
DATASOURCE = load(MON / "grafana" / "datasource.yml")
KUSTOMIZATION = load(MON / "kustomization.yaml")
PROM_DEPLOY = load(MON / "prometheus" / "deployment.yaml")
GRAFANA_DEPLOY = load(MON / "grafana" / "deployment.yaml")
NAMESPACE = load(MON / "namespace.yaml")
RBAC = list(yaml.safe_load_all((MON / "prometheus" / "rbac.yaml").read_text(encoding="utf-8")))
GRAFANA_DOCS = list(yaml.safe_load_all((MON / "grafana" / "service.yaml").read_text(encoding="utf-8")))
PROM_SERVICE = load(MON / "prometheus" / "service.yaml")

RULES = [rule for group in ALERTS["groups"] for rule in group["rules"]]
PANELS = DASHBOARD["panels"]
BUILT_IN = {"up", "ALERTS"}                    # series Prometheus itself creates


def exported_metric_names():
    """Every metric name the real application exposes, with the suffixes Prometheus adds."""
    with TestClient(create_app(Settings())) as client:
        text = client.get("/metrics").text
    names = set()
    for kind_line in re.findall(r"^# TYPE (\S+) (\w+)$", text, re.M):
        name, kind = kind_line
        names.add(name)
        if kind == "counter":
            names.update({name if name.endswith("_total") else name + "_total", name.removesuffix("_total")})
        if kind == "histogram":
            names.update({name + "_bucket", name + "_sum", name + "_count"})
    return names


def metric_names_in(expr):
    return set(re.findall(r"\b(thikana_[a-z0-9_]+|up|ALERTS)\b(?=\s*[{\[(),=!<>+\-*/ ]|$)", expr))


def dashboard_exprs():
    return [t["expr"] for p in PANELS for t in p.get("targets", [])]


# ---- every query refers to a metric that exists -----------------------------------------

def test_every_alert_and_dashboard_query_uses_a_metric_the_service_really_exports():
    known = exported_metric_names() | BUILT_IN
    assert "thikana_http_requests_total" in known and "thikana_model_ready" in known   # the parse worked
    used = set()
    for expr in [r["expr"] for r in RULES] + dashboard_exprs():
        used |= metric_names_in(expr)
    assert used, "no metric names found: the extraction regex is broken"
    assert used - known == set(), f"queries use metrics the service does not export: {used - known}"


def test_the_extraction_really_catches_a_misspelled_metric():
    # Guard for the guard: a typo must be seen as unknown, or the test above proves nothing.
    known = exported_metric_names() | BUILT_IN
    assert metric_names_in('rate(thikana_http_request_total[1m])') - known == {"thikana_http_request_total"}


def test_every_label_a_query_groups_or_filters_by_is_one_the_data_has():
    # `pod` comes from the scrape config's relabelling; the rest are labels the app defines.
    has = {"pod", "namespace", "job", "route", "status", "method", "label", "le", "name", "version",
           "alertname", "alertstate", "severity", "instance"}
    for expr in [r["expr"] for r in RULES] + dashboard_exprs():
        used = set(re.findall(r"\bby \(([^)]*)\)", expr)) | set(re.findall(r"\b(\w+)\s*(?:=~|!=|=)\s*\"", expr))
        flat = {x.strip() for item in used for x in item.split(",")}
        assert flat <= has, f"{expr!r} uses unknown label(s) {flat - has}"


# ---- the scrape configuration ------------------------------------------------------------

def test_prometheus_discovers_only_thikana_pods_in_the_thikana_namespace():
    job = next(j for j in PROM["scrape_configs"] if j["job_name"] == "thikana")
    sd = job["kubernetes_sd_configs"][0]
    assert sd["role"] == "pod" and sd["namespaces"]["names"] == ["thikana"]
    keeps = {r["source_labels"][0]: r["regex"] for r in job["relabel_configs"] if r.get("action") == "keep"}
    assert keeps["__meta_kubernetes_pod_label_app_kubernetes_io_name"] == "thikana"
    assert keeps["__meta_kubernetes_pod_container_port_name"] == "http"
    targets = {r["target_label"] for r in job["relabel_configs"] if "target_label" in r}
    assert {"pod", "namespace"} <= targets             # the `pod` label every per-replica panel uses


def test_the_rule_file_path_in_the_config_matches_where_the_deployment_mounts_it():
    assert PROM["rule_files"] == ["/etc/prometheus/alerts.yml"]
    mount = PROM_DEPLOY["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][0]
    assert mount["mountPath"] == "/etc/prometheus"


# ---- alert rules -------------------------------------------------------------------------

def test_every_alert_has_a_duration_a_severity_and_says_what_to_do():
    names = [r["alert"] for r in RULES]
    assert len(names) == len(set(names)) and names, "duplicate or no alert names"
    for rule in RULES:
        assert rule["alert"].startswith("Thikana")
        assert rule["for"], rule["alert"]                       # no flapping on a single bad scrape
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["annotations"]["summary"] and len(rule["annotations"]["description"]) > 40


def test_there_is_an_alert_for_each_failure_mode_the_drills_exercise():
    assert {"ThikanaTargetDown", "ThikanaModelNotLoaded", "ThikanaHighErrorRate", "ThikanaHighLatency",
            "ThikanaTooFewReplicas", "ThikanaNoTargets", "ThikanaEmptyParsesHigh"} == {r["alert"] for r in RULES}


# ---- dashboard ---------------------------------------------------------------------------

def test_the_dashboard_is_well_formed_and_uses_the_provisioned_datasource():
    assert DASHBOARD["uid"] == "thikana-overview" and DASHBOARD["title"]
    ids = [p["id"] for p in PANELS]
    assert len(ids) == len(set(ids))
    uid = DATASOURCE["datasources"][0]["uid"]
    for p in PANELS:
        assert p["datasource"] == {"type": "prometheus", "uid": uid}, p["title"]
        assert p["gridPos"]["x"] + p["gridPos"]["w"] <= 24, p["title"]
        assert p["title"] and p.get("description"), "every panel explains what it shows"
        for t in p["targets"]:
            assert t["expr"].strip()


def test_panels_do_not_overlap():
    cells = {}
    for p in PANELS:
        g = p["gridPos"]
        for x in range(g["x"], g["x"] + g["w"]):
            for y in range(g["y"], g["y"] + g["h"]):
                assert (x, y) not in cells, f"{p['title']} overlaps {cells[(x, y)]}"
                cells[(x, y)] = p["title"]


def test_the_dashboard_covers_load_balancing_model_health_and_input_drift():
    titles = " | ".join(p["title"] for p in PANELS).lower()
    for needle in ("by pod", "model loaded", "nothing found", "text length", "latency", "alerts"):
        assert needle in titles, needle


# ---- the monitoring pods are as locked down as the app -----------------------------------

@pytest.mark.parametrize("deployment", [PROM_DEPLOY, GRAFANA_DEPLOY], ids=["prometheus", "grafana"])
def test_monitoring_pods_run_non_root_read_only_with_no_capabilities(deployment):
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["securityContext"]["runAsNonRoot"] is True and pod["securityContext"]["runAsUser"] > 0
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    sc = container["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False and sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"] == {"drop": ["ALL"]}
    assert {"requests", "limits"} <= set(container["resources"])
    assert {"readinessProbe", "livenessProbe"} <= set(container)
    for forbidden in ("hostNetwork", "hostPID", "hostIPC"):
        assert not pod.get(forbidden)


def test_the_monitoring_namespace_enforces_the_restricted_profile():
    assert NAMESPACE["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_prometheus_may_only_list_and_watch_pods_in_the_thikana_namespace():
    kinds = {d["kind"] for d in RBAC}
    assert kinds == {"ServiceAccount", "Role", "RoleBinding"}            # no ClusterRole anywhere
    role = next(d for d in RBAC if d["kind"] == "Role")
    binding = next(d for d in RBAC if d["kind"] == "RoleBinding")
    assert role["metadata"]["namespace"] == "thikana" and binding["metadata"]["namespace"] == "thikana"
    assert role["rules"] == [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "watch"]}]
    assert binding["subjects"][0]["namespace"] == "monitoring"
    assert PROM_DEPLOY["spec"]["template"]["spec"]["automountServiceAccountToken"] is True   # discovery needs it


def test_prometheus_has_no_remote_control_endpoints_because_it_has_no_login():
    args = " ".join(PROM_DEPLOY["spec"]["template"]["spec"]["containers"][0]["args"])
    assert "--web.enable-lifecycle" not in args and "--web.enable-admin-api" not in args
    assert "--storage.tsdb.retention.time" in args and "--storage.tsdb.retention.size" in args   # bounded disk


def test_nothing_in_monitoring_is_published_outside_the_cluster():
    services = [PROM_SERVICE] + [d for d in GRAFANA_DOCS if d["kind"] == "Service"]
    assert services and all(s["spec"]["type"] == "ClusterIP" for s in services)


def test_grafana_has_no_default_login_no_sign_up_no_anonymous_access_and_no_phoning_home():
    env = {e["name"]: e for e in GRAFANA_DEPLOY["spec"]["template"]["spec"]["containers"][0]["env"]}
    password = env["GF_SECURITY_ADMIN_PASSWORD"]
    assert "value" not in password                                          # never a literal in git
    assert password["valueFrom"]["secretKeyRef"] == {"name": "grafana-admin", "key": "admin-password"}
    assert env["GF_AUTH_ANONYMOUS_ENABLED"]["value"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"]["value"] == "false"
    assert env["GF_ANALYTICS_REPORTING_ENABLED"]["value"] == "false"
    assert GRAFANA_DEPLOY["spec"]["template"]["spec"]["automountServiceAccountToken"] is False


def test_images_are_pinned_by_version_and_digest_never_latest():
    images = {i["name"]: i for i in KUSTOMIZATION["images"]}
    assert set(images) == {"prometheus", "grafana"}
    for name, image in images.items():
        assert re.fullmatch(r"v?\d+\.\d+\.\d+", str(image["newTag"])), f"{name}: tag {image['newTag']!r}"
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", image["digest"]), f"{name}: digest {image.get('digest')!r}"
    for deployment in (PROM_DEPLOY, GRAFANA_DEPLOY):
        assert ":" not in deployment["spec"]["template"]["spec"]["containers"][0]["image"]   # set in one place


def test_no_namespace_transformer_which_would_move_the_role_out_of_thikana():
    assert "namespace" not in KUSTOMIZATION


# ---- rendered output (needs kubectl) -----------------------------------------------------

@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_rendered_output_has_every_object_in_the_right_namespace_with_wired_configmaps():
    out = subprocess.run(["kubectl", "kustomize", str(MON)], capture_output=True, text=True, check=True).stdout
    docs = [d for d in yaml.safe_load_all(out) if d]
    for d in docs:
        if d["kind"] == "Namespace":
            continue
        expected = "thikana" if d["kind"] in {"Role", "RoleBinding"} else "monitoring"
        assert d["metadata"]["namespace"] == expected, f"{d['kind']} {d['metadata']['name']}"
    assert not any(d["kind"] == "Secret" for d in docs)
    configs = {d["metadata"]["name"] for d in docs if d["kind"] == "ConfigMap"}
    assert len(configs) == 4 and all(re.fullmatch(r"[a-z-]+-[a-z0-9]{8,12}", c) for c in configs)
    referenced = set()
    for d in docs:
        if d["kind"] == "Deployment":
            referenced |= {v["configMap"]["name"] for v in d["spec"]["template"]["spec"]["volumes"] if "configMap" in v}
    assert referenced == configs                                    # none missing, none unused
    for d in docs:
        if d["kind"] == "Deployment":
            assert re.fullmatch(r"[\w./-]+:[\w.]+@sha256:[0-9a-f]{64}|[\w./-]+@sha256:[0-9a-f]{64}",
                                d["spec"]["template"]["spec"]["containers"][0]["image"])


# ---- Prometheus's own checker, when Docker is available ----------------------------------

def _promtool(args, mounts):
    image = next(i for i in KUSTOMIZATION["images"] if i["name"] == "prometheus")
    ref = f"{image['newName']}@{image['digest']}"
    probe = subprocess.run(["docker", "image", "inspect", ref], capture_output=True)
    if probe.returncode != 0:
        pulled = subprocess.run(["docker", "pull", ref], capture_output=True, timeout=300)
        if pulled.returncode != 0:
            pytest.skip("the pinned Prometheus image could not be pulled")
    cmd = ["docker", "run", "--rm", "--entrypoint", "promtool"]
    for host, container in mounts:
        cmd += ["-v", f"{host}:{container}:ro"]
    return subprocess.run(cmd + [ref, *args], capture_output=True, text=True, timeout=300)


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_promtool_accepts_the_config_and_the_alert_rules_unit_tests_pass():
    mounts = [(str(MON / "prometheus"), "/etc/prometheus"), (str(MON), "/w")]
    check = _promtool(["check", "config", "/etc/prometheus/prometheus.yml"], mounts)
    assert check.returncode == 0, check.stdout + check.stderr
    tests = _promtool(["test", "rules", "/w/tests/alerts_test.yaml"], mounts)
    assert tests.returncode == 0, tests.stdout + tests.stderr
    assert "SUCCESS" in tests.stdout
