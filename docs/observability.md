# Observability: Prometheus, Grafana and alerts

Prometheus and Grafana run in their own `monitoring` namespace on the local cluster and
watch the three `thikana` replicas. Everything below was run and measured on that cluster
(one laptop, one node, Docker given 3.5 GB); where something was only unit-tested or not
done, it says so.

```
k8s/monitoring/
  namespace.yaml                  enforces the "restricted" Pod Security profile
  prometheus/prometheus.yml       scrape config: finds the pods through the Kubernetes API
  prometheus/alerts.yml           7 alert rules
  prometheus/rbac.yaml            a Role in the thikana namespace: list/watch pods, nothing else
  prometheus/deployment.yaml      1 replica, locked down, 24 h retention, NOT persistent
  grafana/datasource.yml          Prometheus as a provisioned data source
  grafana/thikana-dashboard.json  the dashboard, as code (15 panels)
  grafana/deployment.yaml         1 replica, locked down; admin password from a Secret
  tests/alerts_test.yaml          promtool unit tests for the alert rules
  kustomization.yaml              images pinned by tag AND digest; hashed ConfigMaps
tests/test_monitoring.py          ties every query to a metric the service really exports
```

## Use it

Run these in PowerShell. The first line is the folder that contains `k8s/`.

```powershell
cd E:\My-Projects\cloud-native-ml-platform\.claude\worktrees\devops-portfolio-project-2a4bd1
```

**1. Create Grafana's admin password in the cluster** (once; never in git, never printed).
The pod refuses to start without it, on purpose, because Grafana's default login is `admin/admin`:

```powershell
kubectl apply -f k8s/monitoring/namespace.yaml
$chars = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"; $b = New-Object byte[] 24
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
$pw = -join ($b | ForEach-Object { $chars[$_ % $chars.Length] })
kubectl -n monitoring create secret generic grafana-admin --from-literal=admin-password=$pw
Remove-Variable pw, b
```

**2. Deploy, then wait.** A *fresh* Grafana needs about **2 min 47 s** to start (167 s measured),
so be patient; after a container restart it took 43 s.

```powershell
kubectl apply -k k8s/monitoring
kubectl -n monitoring rollout status deployment/prometheus
kubectl -n monitoring rollout status deployment/grafana
```

**3. Open the UIs.** Neither is published outside the cluster; `port-forward` listens on
127.0.0.1 only. Run each in its own terminal and leave it open:

```powershell
kubectl -n monitoring port-forward svc/grafana 3000:3000
```

```powershell
kubectl -n monitoring port-forward svc/prometheus 9090:9090
```

Grafana: <http://localhost:3000> (dashboard: *Thikana > Thikana overview*), user `admin`. To get the
password **onto your clipboard without displaying it**:

```powershell
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl -n monitoring get secret grafana-admin -o jsonpath="{.data.admin-password}"))) | Set-Clipboard
```

Prometheus: <http://localhost:9090> (*Status > Targets*, *Alerts*, *Graph*). It has **no login**,
which is why it is never exposed and why its remote-control endpoints are switched off.

Remove it all: `kubectl delete -k k8s/monitoring` then `kubectl delete secret grafana-admin -n monitoring`
(not run in this session).

## What is monitored

Prometheus discovers the pods itself (a Role limited to the `thikana` namespace: list and watch
pods), so a new replica is scraped within seconds and a deleted one disappears. It scrapes each pod
directly, which is what makes per-replica series, and so load balancing, visible.

The service's own metrics (`thikana_*`) cover requests, latency, **what the model predicts**
(entities by label, empty parses, input length) and whether a model is loaded. The model signals
exist because the failure ML systems have most often is the quiet one: fast, up, answering 200,
and wrong. **A test checks that every query in the rules and the dashboard uses a metric the
service really exports**, and that the check itself would catch a typo, because a dashboard panel
with a misspelled metric shows an empty graph forever.

**Are the metrics true?** I sent exactly 300 requests (10% of them inputs that yield no entity) and
compared what the client counted with what Prometheus recorded: requests, addresses parsed, empty
parses (30 vs 30) and all nine per-label entity counts matched **exactly**.

### The dashboard (15 panels, every one has a description)

Status row: replicas up, models loaded, API requests/s, 5xx share, p95 parse latency, alerts firing.
Then: parse requests/s **by pod** (load balancing), API requests/s by status, latency p50/p95/p99,
model loaded by pod, entities found by label, share of addresses with nothing found, submitted text
length, model identity by pod, active alerts. Every panel's query was run through **Grafana's own
API** under live traffic: **14 of 15 return data**; the 15th (the alerts table) is empty because
nothing is firing, which is correct.

## Alerts

| Alert | Fires when | For | Fired for real? |
|---|---|---|---|
| `ThikanaTargetDown` | a pod's `/metrics` cannot be read | 1 m | not as a true positive (see below); a *planned* deletion correctly did **not** fire it |
| `ThikanaNoTargets` | no `thikana` pods are scraped at all | 2 m | **yes**: scaled to 0, fired at 163 s |
| `ThikanaTooFewReplicas` | fewer than 2 replicas up | 2 m | **yes**: scaled to 1, fired at 144 s |
| `ThikanaModelNotLoaded` | a pod is up but has no model | 30 s | **yes**: missing model file, fired at 91 s and 115 s after deploy (two runs) |
| `ThikanaHighErrorRate` | more than 5% of **API** requests are 5xx | 5 m | a **false alarm** fired once (below), fixed; the true positive was only unit-tested |
| `ThikanaHighLatency` | p95 of `/api/v1/parse` above 0.5 s | 5 m | unit-tested only |
| `ThikanaEmptyParsesHigh` | over 20% of addresses yield no entity | 15 m | unit-tested only |

All seven rules were loaded by the running Prometheus with `health=ok`, and the three unit-tested-only ones
were evaluated against live traffic (58 req/s: error ratio 0, p95 84 ms, empty share 0). The thresholds are
**not calibrated on real traffic** (there is none); they are starting points.

**What "unit-tested" means here.** `promtool test rules` runs each rule against synthetic series, with a case
where it must fire and one where it must stay silent, at the production 15-second evaluation cadence.
I deliberately broke the rules in 9 distinct ways (a threshold, a duration, a route filter, a status pattern,
a wrong value, and reverting the two fixes recorded below); the tests caught every one.

## What the drills found (kept because they teach)

1. **A false alarm, fired for real.** In the missing-model drill `ThikanaHighErrorRate` went pending at
   79 s and then **fired** (at 6.7%, peaking at 11.1%) while every real request through the load balancer
   was a 200. Cause: the service counts *every* request, including Kubernetes's readiness, liveness and
   startup probes and Prometheus's own scrapes, and at idle those are **99.5%** of all requests
   (`/readyz` 0.68/s, `/healthz` 0.27/s, `/metrics` 0.20/s against 0.003/s of real traffic). One pod failing
   its readiness probe made 503s a double-digit share. Fix: the alert and the three affected panels use API
   routes only. A regression test reproduces it and fails against the old rule; the same drill rerun for
   170 s no longer raised it.
2. **Two attempts at one timer.** I first argued `ThikanaTargetDown` and `ThikanaModelNotLoaded` must be
   30 s, because a frozen pod is restarted by its liveness probe about 67 s after freezing (so it is
   unscrapeable for ~57 s) and a pod with no model is restarted by its startup probe about every 60 s,
   either of which resets a 1-minute timer. The drills confirmed the cases (frozen pod: pending at 27 s, fired
   at 42 s, resolved at ~107 s). They also showed the cost: **deleting or scaling down a healthy pod leaves
   `up == 0` for about 34 s**, and a scale-down crossed 30 s, so `TargetDown` **paged on a planned change**.
   `ThikanaModelNotLoaded` stays at 30 s (a healthy pod reports its model within a second). `TargetDown` went
   back to **1 minute**: it will not fire for a hang the kubelet cures within ~67 s, which self-heals; the
   right signal for that is a container-restart count, which needs `kube-state-metrics` (not installed).
   Verified: two planned pod deletions produced `pending` only. The unit test models termination with a
   staleness marker, which is what Prometheus really writes, and fails against the 30 s version.
3. **A dashboard that said "No data" exactly when healthy.** Prometheus only creates a `5xx` series once a 5xx
   has happened, so the 5xx-share panel was empty on a healthy service. Fixed (`or vector(0)`); found by
   running every panel's query, not by reading the JSON.
4. **Grafana 13 starts slowly, and I killed it three times.** A 2-minute startup window was shorter than the
   167 s a fresh Grafana needs, so kubelet restarted it just before it finished. Window now 5 minutes.
5. **Tooling that lied.** (a) My first image-scan script printed "0 findings" when Trivy had actually failed;
   rerun with errors visible, it found 10 fixable HIGH in the Prometheus version I had picked. (b) A test of my
   own alert-test file evaluated at 1-minute cadence while production evaluates every 15 s, which made a
   30 s alert look late. (c) In PowerShell 5.1, double quotes inside `curl.exe` arguments are silently
   stripped, so queries containing `{route="..."}` returned nothing: I proved the metrics were fine by
   querying from Python. (d) A kill-everything line in one of my commands was rightly refused: it would
   have stopped port-forwards I did not start.
6. **The cluster restarted itself mid-work.** About 3 minutes before one check, every pod restarted once
   (the scheduler logged a start 52 s earlier), while your other containers kept running (up for hours) and
   the Docker session was unchanged. I could not find the cause. The VM is under memory pressure (about
   500-650 MB of swap in use), which is a plausible contributor, not a shown one.

### Something about the model that the metrics exposed

The "nothing found" signal is **weaker than I expected**: the parser labels almost any text. `the`, `!!!`
and `12` come back as `HOUSE`, `x y z` as `LANDMARK`; it returns no entity only for pure punctuation
(`...`, `-`, `,,,`). So `ThikanaEmptyParsesHigh` will mostly catch junk made of punctuation, not drift in
real-looking input. A better drift signal would be a per-address confidence (the CRF can report marginal
probabilities); the service does not export one yet, so none is claimed.

## What it costs, measured

| | |
|---|---|
| Prometheus memory | 79-81 MiB (request 128 Mi, limit 512 Mi), CPU 1-16% |
| Grafana memory | 272-322 MiB (request 256 Mi, limit 512 Mi), CPU up to 107% (its 1-core limit) |
| Grafana start | 167 s fresh, 43 s after a container restart (its database survives in an `emptyDir`) |
| Healthy extra replica start | created to started 8 s, then 6 s to Ready, one sample taken after monitoring was added; before it, 1-2 s and 6-10 s in total, so monitoring made pods slower to start on this VM |

Docker has 3.5 GB and was already using swap. Giving Docker Desktop more memory is the first thing to
do if this is slow or unstable.

## Images (pinned, and scanned before pinning)

| Image | Pinned | Trivy 0.76.1: HIGH/CRITICAL with a fix available |
|---|---|---|
| `prom/prometheus` | `v3.15.1@sha256:fa3302279710...` | **0** (v3.15.0: 10, rejected) |
| `grafana/grafana` | `13.3.0@sha256:488984b716c0...` | **39** (13.2.4: 78, rejected) |

The Grafana findings are the Go standard library and `golang.org/x/net` inside Grafana's own binaries (a few
CVEs repeated across several of them, scanned 2026-10-27). Only Grafana rebuilding with a newer Go can clear
them. **Grafana is therefore cluster-internal only and must not be exposed publicly until a rebuilt image is
pinned.** Re-scan when bumping.

## Limits you should know

- **Nothing is notified.** There is no Alertmanager: a firing alert shows in Prometheus and in the dashboard,
  and that is all. Delivery needs a Slack webhook or SMTP credential, i.e. a secret and a decision.
- **No persistence.** History is in an `emptyDir`: lost whenever the pod is *replaced* (every config change),
  kept across a mere container restart.
- **No `kube-state-metrics`, no cAdvisor, no node metrics.** So no container-restart or OOM alerts, and no
  CPU/memory graphs in Grafana (the numbers above came from `docker stats`).
- **`/metrics` is served on the same port as the API.** Today the local load balancer answers only on
  localhost (tested: it does not answer on the LAN address). **On any public host it must be blocked at the
  ingress**, or anyone can read request counts and model internals.
- **Probe traffic is counted as requests** by the service; the rules and panels above now exclude it, but the
  raw metric still includes it. Unlabelled consumers of `thikana_http_requests_total` must do the same.
- **Alert thresholds are uncalibrated**, and three alerts were only unit-tested (above).
- **Grafana's password is a Kubernetes Secret**: base64, not encrypted; anyone who can read secrets in the
  namespace can read it.
- **The monitoring tests need Docker** for `promtool` and skip without it (and `kubectl` for the rendered
  check); neither has run on the GitHub runner yet.
- **Single replicas, one node, a tight VM** (see above), and one unexplained control-plane restart.
