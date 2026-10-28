# Thikana: a Bangladeshi address parser

[![CI](https://github.com/iftakhar005/cloud-native-ml-platform/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/iftakhar005/cloud-native-ml-platform/actions/workflows/ci.yml)

Thikana (ঠিকানা) splits one free-text Bangladeshi address, written in Bangla,
English or a mix, into labelled parts: house, road, block, area, upazila, district,
division, postcode and landmark.

```
House 12, Road 5, Mirpur-10, Dhaka-1216
  HOUSE: House 12   ROAD: Road 5   AREA: Mirpur-10   DISTRICT: Dhaka   POSTCODE: 1216
```

**Try it:** <https://thikana-ub5e.onrender.com>. It runs on a free host that sleeps after
15 idle minutes, so the first visit can take a minute or two while it wakes. If that link
is down, the host's free tier has probably been turned off or changed (see
[`docs/public-hosting.md`](docs/public-hosting.md)).

It is a **learning project**, built to practise the whole path from a trained model to a
running service: Docker, Kubernetes, CI/CD, monitoring and security.

## Honest status

- **A prototype, not a product.** No uptime promise, no real users, no performance claim
  beyond the measurements in `docs/`.
- **The model learned from synthetic addresses**, generated from a public gazetteer of
  districts, upazilas and post offices. It has never been scored on real addresses
  (`data/real/` is empty).
- **The hand-written test sets are not real data.** An AI assistant wrote them from general
  knowledge of Bangladeshi addresses, and the same author wrote the generator, so the real
  error rate is probably worse than the numbers below.
- **It labels any text.** It has no way to say "this is not an address".
- **Known weaknesses.** Bare village and union names with no cue word (`বুধড়া, গুনবতী`) used
  to be labelled as upazilas; a generator fix plus known-name features cut that (see Model
  results), but it is only measured on made-up villages. Typos inside keywords and names
  (`Hosue 9`) and the occasional real upazila labelled as an area remain.

## What is in it

| Part | What it is | Details |
|---|---|---|
| Model | A linear-chain CRF (python-crfsuite) tagging tokens with BIO labels. Features describe each token's surface form and its neighbours, plus a district-name memory and known-name lists (districts, divisions, upazilas) | [`docs/results.md`](docs/results.md), [`docs/label-schema.md`](docs/label-schema.md) |
| API | FastAPI: `POST /api/v1/parse`, batch, model info, `/healthz`, `/readyz`, Prometheus `/metrics` | [`docs/api.md`](docs/api.md) |
| Web page | Four static files served by the same process: no framework, no CDN, no cookies. Parses one address, or CSV / TSV / TXT files (up to 5 at once, 500 rows each) and gives back a CSV | [`thikana/web/`](thikana/web), [`docs/api.md`](docs/api.md) |
| Container | Multi-stage Docker image, non-root, digest-pinned base, runs read-only with all capabilities dropped | [`docs/docker.md`](docs/docker.md) |
| CI/CD | GitHub Actions: tests, train, quality gate, build, smoke test, vulnerability scan, publish to GHCR | [`docs/ci.md`](docs/ci.md) |
| Kubernetes | Three replicas on Docker Desktop's built-in cluster, behind a LoadBalancer | [`docs/kubernetes.md`](docs/kubernetes.md) |
| Monitoring | Prometheus, Grafana (15-panel dashboard) and 7 alert rules | [`docs/observability.md`](docs/observability.md) |
| Public hosting | Render's free tier, with a public mode and a rate limiter | [`docs/public-hosting.md`](docs/public-hosting.md) |

## How it fits together

```
 git push --> GitHub Actions
                verify: tests -> train model -> quality gate
                image:  build -> smoke test -> Trivy scan -> push (main only)
                              |
                              v
        GHCR   ghcr.io/iftakhar005/thikana-api@sha256:<digest>
                    |                                   |
        public, free |                                   | local, for learning
                    v                                   v
       Render free web service            Docker Desktop Kubernetes (1 node)
       public mode, rate limit              LoadBalancer  localhost:8088
       sleeps when idle                        -> Service -> 3 pods (rolling updates)
                                             Prometheus + Grafana (internal only)
```

Two separate copies of the app run: the public one on Render, which needs nothing on the
author's laptop, and a local Kubernetes one used for practising orchestration and
monitoring. Nothing on the local cluster is reachable from the internet.

## Kubernetes and the load balancer

The local cluster is **Docker Desktop's built-in Kubernetes** (v1.32, a **single node**). It
is not Minikube or kind. Manifests are in [`k8s/`](k8s), built with Kustomize:

| Path | Purpose |
|---|---|
| `k8s/base/` | Namespace, ServiceAccount, Deployment (3 replicas), ClusterIP Service, PodDisruptionBudget |
| `k8s/overlays/local/` | Adds a `LoadBalancer` Service that Docker Desktop publishes on `localhost:8088`; runs a locally built image |
| `k8s/overlays/ghcr/` | Same, but runs the image CI published, pinned by digest |
| `k8s/monitoring/` | Prometheus, Grafana and alert rules in their own namespace |

How it is set up, and why (each choice was exercised on the cluster; see the doc):

- **Service and LoadBalancer.** The base `ClusterIP` Service gives the ready pods one
  stable address. The local overlay adds a `LoadBalancer` Service in front of the same pods.
  Traffic is balanced **per connection, not per request**: with a new connection per request
  the three pods answered 32.9%, 33.7% and 33.4% of 3,186 requests, while a client that keeps
  one connection open stays on one pod.
- **Three probes, three questions.** *Startup*: is the model loaded? *Readiness*: send
  traffic now? (failing removes the pod from the Service without restarting it.) *Liveness*:
  is the process wedged? (it deliberately ignores the model, because a restart cannot fix a
  missing model.)
- **Rolling updates** with `maxUnavailable: 0, maxSurge: 1`: a new pod must be Ready before an
  old one goes. A bad image and a bad model were both tried on purpose; the old pods kept
  serving.
- **Locked-down pods.** Non-root user, read-only root filesystem, all capabilities dropped,
  no service-account token, and the namespace enforces the `restricted` Pod Security
  profile.
- **A PodDisruptionBudget**, a generated ConfigMap whose content hash rolls the pods on any
  config change, and resource requests and limits taken from measurement (about 52 MiB of
  memory per pod under load).

Measured on one laptop (12 CPUs, load generator on the same machine, single 24 s runs).
Comparisons between rows are meaningful; none of it is a capacity claim:

| Replicas | Requests/s | p50 / p95 latency (ms) |
|---|---|---|
| 1 | 148 | 187 / 360-375 |
| 2 | 328 | 79-94 / 172-187 |
| 3 | 439 | 63-78 / 110-125 |
| 4 | 578 | 47-62 / 93-94 |

A graceful pod delete under load produced 0 errors in 5,077 requests, and so did a rolling
update and a rollback. A hard crash of one pod failed 114 of 4,390 requests (2.6%), all within
about 3 seconds. Known limits, also in the doc: one node
means no protection from a crashed computer, no Ingress or TLS, no autoscaling and no
NetworkPolicy.

## Monitoring

Prometheus finds the pods through the Kubernetes API (a Role that can only list and watch
pods in one namespace), and Grafana shows a provisioned 15-panel dashboard. Both are
`ClusterIP` only; you reach them with `kubectl port-forward`. Seven alert rules are
unit-tested with `promtool`. Three were fired for real, by scaling to zero, scaling to one
and deleting the model file. The other four are only unit-tested or were not a true positive,
and the thresholds are starting points, not calibrated on real traffic. The drills also found
a false alarm and fixed it; the story is in `docs/observability.md`.

## CI/CD and supply chain

Two jobs run on every pull request and push, and a third is off by default:

- **verify** (read-only token): install, run the tests, train the production model, then run
  a **quality gate** that fails the build if the freshly trained model scores below a floor on
  the hand-written sets. It is a regression check, not an evaluation.
- **image** (the only job that can write packages): build, run the image as Kubernetes will
  (non-root, read-only), smoke-test it both normally and in public mode, scan it with Trivy,
  and push `ghcr.io/<owner>/thikana-api:<full-commit-sha>` only on `main`. There is no
  `latest` tag.
- **deploy** (optional, disabled until the variable `RENDER_DEPLOY_ENABLED` is `true`): asks
  Render to run exactly the image digest the build just published.

No secret is stored in the repository. Every GitHub Action is pinned to a commit SHA, the
scanner is pinned by image digest, and the Docker base image is pinned by digest. Details,
including what Trivy found, are in `docs/ci.md`.

## Public hosting

[Render's free web service](docs/public-hosting.md) runs the image (0.1 CPU, 512 MB), chosen
after comparing free hosts from their official documentation, because zero cost mattered
more than always-on availability. In public mode `/metrics`, `/docs`, `/redoc` and
`/openapi.json` return 404, a strict Content-Security-Policy and other security headers are
sent, a per-client rate limiter protects the small CPU allowance, and the app logs only
counts, never address text or client addresses. The host may keep its own request logs,
which the app cannot see. `scripts/check_public.py <url>` audits a deployed URL from outside
(21 checks).

## Model results

Entity-level micro F1 (start, end and label must all match). The full table, with what each
number does and does not mean, is in [`docs/results.md`](docs/results.md).

| Evaluation | Rule baseline | Production CRF |
|---|---|---|
| Hand-written v4 (65 addresses) | 0.918 | 0.952 (0.897 before the village work) |
| Hand-written v7 (51 addresses), sealed and scored once | 0.981 | 0.981 (0.818 before the village work) |

On v4 the difference to the baseline is inside the noise (paired bootstrap interval includes
0), and on v7 the two are tied: these sets turn on whether a name is in the gazetteer, which a
dictionary answers exactly. Both sets are small, hand-written by the same author as the
generator, and not real data, so they say nothing about real addresses. The village work and
the decision to add known-name features are in [`docs/results.md`](docs/results.md).

## Run it yourself

Needs Python 3.12. Commands are for PowerShell on Windows; Docker and kubectl are optional.

```powershell
git clone https://github.com/iftakhar005/cloud-native-ml-platform.git
cd cloud-native-ml-platform
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements\dev.txt

python -m pytest -q                      # the test suite
python -m thikana.training.train_all     # trains models/ (gitignored, rebuilt from code and data)
python -m thikana.training.gate          # the CI quality gate, locally
python -m uvicorn thikana.api.main:app --port 8000
```

Open <http://localhost:8000> for the page, or <http://localhost:8000/docs> for the API
documentation. To run it in a container, see [`docs/docker.md`](docs/docker.md). To run it on
Kubernetes (Docker Desktop with Kubernetes enabled), see [`docs/kubernetes.md`](docs/kubernetes.md).

## Repository layout

```
thikana/            api/ (FastAPI), web/ (the page), training/ (data generator, training, gate), model, features
data/               gazetteer/ (reference data), handwritten/ (evaluation sets), real/ (empty, gitignored)
k8s/                base, overlays (local, ghcr) and monitoring manifests
scripts/            loadtest.py, check_public.py
tests/              the pytest suite, including JavaScript tests run through Node
docs/               one document per topic, each with what was verified and what was not
requirements/       pinned dependencies for serving, training and development
.github/workflows/  ci.yml
```

## What is not done

No real-address evaluation, no separate village or union labels, no Ingress or TLS on the
local cluster, no autoscaling, no persistent monitoring storage, and no licence file yet.
