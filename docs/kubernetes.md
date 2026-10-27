# Kubernetes

The API as three replicas on a local Kubernetes cluster (Docker Desktop's built-in one,
Kubernetes v1.32, **one node**). Everything below was run on that cluster and measured,
not assumed; where something was not measured, it says so.

```
k8s/base/                        the reusable part
  namespace.yaml                 enforces the "restricted" Pod Security profile
  serviceaccount.yaml            an identity that can do nothing, no token mounted
  deployment.yaml                3 replicas, probes, locked-down pod, rolling update
  service.yaml                   ClusterIP: the stable address of "the ready pods"
  pdb.yaml                       at most one voluntary disruption at a time
  kustomization.yaml             generated ConfigMap (its hash rolls the pods on change)
k8s/overlays/local/              the part specific to a laptop
  service-lb.yaml                LoadBalancer on localhost:8088 (Docker Desktop publishes it)
  kustomization.yaml             pins the image to a commit tag
scripts/loadtest.py              the load generator used for every measurement below
```

## Deploy, look, remove

Run these in PowerShell from the folder that contains `k8s/` (in this project's setup,
the worktree).

```powershell
cd E:\My-Projects\cloud-native-ml-platform\.claude\worktrees\devops-portfolio-project-2a4bd1
```

Build the image the overlay names (the tag is the commit, never `latest`):

```powershell
$sha = git rev-parse --short HEAD
docker build -t thikana-api:$sha --build-arg GIT_SHA=$sha .
```

Put that tag in `k8s/overlays/local/kustomization.yaml` (`newTag`), then:

```powershell
kubectl apply -k k8s/overlays/local
kubectl -n thikana rollout status deployment/thikana
kubectl -n thikana get pods
```

Ask it a question and see *which pod* answered:

```powershell
curl.exe -s -D - -o NUL --data-binary "@request.json" -H "Content-Type: application/json" http://localhost:8088/api/v1/parse
```

Look for `x-thikana-instance: thikana-<hash>-<id>`. **Trust that header, not the port**:
another container on the machine can own the port and answer with its own 404 (it did).

```powershell
kubectl delete -k k8s/overlays/local        # not run in this session: it should remove everything above, namespace included
```

Useful afterwards: `kubectl -n thikana rollout undo deployment/thikana` (previous revision),
`kubectl -n thikana scale deployment/thikana --replicas=N` (temporary: the file says 3),
`kubectl -n thikana logs deploy/thikana` (one JSON line per request, never the address),
`kubectl -n thikana describe pod <name>` (why a pod is not ready: the probe events).

## What each choice is for

| Choice | Why | Verified how |
|---|---|---|
| 3 replicas | something to balance; one can die without an outage | killed one under load (below) |
| Three probes, three questions | *startup*: model loaded? *readiness*: send traffic now? (failing removes the pod from the Service, no restart) *liveness*: is the process wedged? (failing restarts it; it does not look at the model, because a restart cannot fix a missing model) | each one triggered on purpose (below) |
| `maxUnavailable: 0`, `maxSurge: 1` | an update starts a new pod and waits until it is Ready before removing an old one | rolling update, bad image and bad model drills |
| Pod: non-root uid 10001, seccomp `RuntimeDefault` | the uid is the one the Dockerfile creates; a test checks they agree | the cluster accepted it under the `restricted` profile |
| Container: no privilege escalation, **read-only root filesystem**, all capabilities dropped | the service writes nothing to disk and needs no privilege | pods run and answer normally |
| Namespace label `pod-security...enforce: restricted` | the *cluster* rejects a pod that is not restricted, even if someone edits the Deployment carelessly | accepted; **not** tested by deploying a violating pod |
| No service-account token mounted | the service never talks to the Kubernetes API | static test |
| Generated ConfigMap | its name carries a content hash, so a config change *is* a rollout | changed a value: new pods, old ones replaced, then undone |
| `preStop` sleep 5 s | the pod is removed from the Service and signalled at the same moment; a request can still arrive just after | graceful delete: 0 errors in 5,077 requests (but see crash) |
| Image tag = commit, `IfNotPresent` | a tag never changes meaning, and a local image is used as is | deployed `thikana-api:e8e5c4c` |
| `X-Thikana-Instance` header | makes load balancing visible | used throughout |

Resources: **requests** cpu 100m / memory 64Mi, **limits** cpu 1 / memory 128Mi. Memory
under sustained load peaked at **52.1 MiB** per pod (idle: 42.6 MiB), so the memory
numbers have headroom: the limit kills the pod when exceeded, hence 2.5x the peak. CPU is
different: a saturated pod used about **one full core** (peak samples 101-105%), so the
CPU limit of 1 is binding under load, and the 100m request is a scheduling promise far
below what a busy pod uses. That is deliberate (a laptop with one node, nothing competing)
but it would not be a fair request on a shared cluster.

## What was measured

All of this is one laptop: 12 CPUs, Docker given 3.7 GB of memory, one node, the load
generator on the same machine competing for CPU, six made-up addresses. **Comparisons
between rows are meaningful; none of these is a capacity claim.** Each throughput figure
is a single 24-second run: the run-to-run noise was not measured.

### Startup

A pod takes **about 6-10 s from creation to Ready** (container started after 1-2 s, then
5-8 s to pass readiness; the readiness probe's 5 s period dominates, not model loading).

### Load balancing

Traffic is balanced **per connection, not per request**.

| Client behaviour | Which pod answered |
|---|---|
| a new connection per request, 3,186 requests | 32.9% / 33.7% / 33.4% |
| 12 long-lived (keep-alive) connections, 5,023 requests | 32.9% / 33.1% / 33.9% |
| 2 keep-alive connections, six runs | both on one pod in 2 runs, split 50/50 over two pods in 4 |

So a client that keeps one connection open stays on one pod; with few connections the
spread is lumpy, with many it evens out. A single pod can look "busy" while two sit idle.
`kubectl port-forward` is documented to connect to a single pod, so it cannot show
balancing (not tested here; the local `LoadBalancer` was used instead). Also, on one node the replicas share one machine: the
balancer spreads load across pods, not across computers.

### Throughput with replica count (4 load processes, 32 keep-alive connections)

| Replicas | req/s | p50 / p95 latency (ms) | Pod CPU | Pod memory |
|---|---|---|---|---|
| 1 | 148 | 187 / 360-375 | ~103% | 52.1 MiB |
| 2 | 328 | 79-94 / 172-187 | ~105% | 50.7 MiB |
| 3 | 439 | 63-78 / 110-125 | ~101% | 50.9 MiB |
| 4 | 578 | 47-62 / 93-94 | ~105% | 50.9 MiB |

Roughly linear while every pod sits at about one core, which is what a CPU-bound
single-process service does. Beyond 4 was not tried; where the laptop or the load
generator becomes the limit was not found.

### Failure drills (8 workers, a new connection per request unless noted)

| What was done | What clients saw | What the cluster did |
|---|---|---|
| **Graceful pod delete** under load | **0 errors / 5,077** | replacement Ready; back to 3 Ready pods in ~16 s |
| **Hard crash** (SIGKILL to a pod's container) | **114 errors / 4,390 (2.6%)**, all within ~3 s: 71 connection reset, 33 remote disconnected, 10 aborted | same pod restarted in place, Ready after 10.8 s (restart count 1, exit 137) |
| **Rolling update** (ConfigMap change) | **0 errors / 5,121** | 3 pods replaced one at a time in 47.6 s |
| **Rollback** (`rollout undo`) | **0 errors / 8,024** | back to the previous config in 36.6 s; matches the committed files |
| **Bad release** (image tag that does not exist) | **0 errors / 5,824** | the new pod sat in `ImagePullBackOff`; the 3 old pods kept serving; `rollout status` exited 1 |
| **Missing model file** in new pods | all 16,273 successful answers came from the old pods; the unready pod got none | stayed `0/1`; after ~60 s the startup probe killed and restarted it (see below) |
| **Frozen process** (SIGSTOP; liveness drill), 12 keep-alive connections | **4 timeouts / 30,113** (the connections pinned to the frozen pod, until the client's 10 s timeout) | readiness failed at +10 s (out of the Service); restarted at +67 s; Ready at +75 s |

What to take from it:

- **Planned changes are invisible; crashes are not.** The probes, `maxUnavailable: 0` and
  the `preStop` wait make updates, rollbacks and even a broken release cost nothing. A
  hard crash still fails the requests that were already on that pod. Parsing an address
  is idempotent, so a client or ingress can **safely retry** (nothing here retries yet).
- **A hang is detected slowly.** Readiness needs 2 failures x 5 s = ~10 s, during which a
  request to the frozen pod simply waits. A client without a timeout waits much longer.
- **The missing-model design, corrected.** The service stays up and unready (`/healthz`
  200, `/readyz` 503, no crash) as designed, and that part held. But in Kubernetes the
  *startup* probe calls `/readyz`, so "never became ready within 60 s" turns into a
  restart, repeatedly. That is visible (the restart count climbs) and the old pods keep
  serving, so it is acceptable, but my earlier statement that this case would not restart
  was wrong for Kubernetes.

One thing seen and not explained: during the graceful delete and the rolling update,
throughput fell for 13-45 s by more than losing one pod's share would explain. New pods
loading a model while the load generator competes for CPU is a plausible cause; it was
not isolated.

## Mistakes this process found (kept because they teach)

1. **An overlay's resource missed the namespace.** The base sets `namespace: thikana`, but
   that does not reach resources an overlay adds, so the LoadBalancer Service landed in
   `default` with no pods behind it. Found by applying, not by reading. The overlay now
   sets the namespace itself; two tests guard it.
2. **A port that was "free" was not.** Another container took 8080 after Docker restarted
   and answered my request with its own 404. The missing `X-Thikana-Instance` header gave
   it away. The local Service now uses 8088, and the header, not the port, decides whose
   answer it was.
3. **A load tool that measured the wrong thing, twice.** On Windows, Python tried IPv6
   first and every connection waited out a 10 s timeout (10.4 s per request instead of
   31 ms); the tool now connects to `127.0.0.1`. Then, in a long run, 2,635 errors
   looked like a service failure; they were the load generator **running out of local
   ports** (`OSError 10048`; a new connection per request leaves each one in `TIME_WAIT`
   for about two minutes, and Windows offers about 16,000). Reproduced on a healthy
   cluster at the same ceiling, and the tool now says so. The crash drill's errors were
   a different kind (reset/disconnected) and stand.
4. **A test that could not fail.** The first test for the IPv6 fix passed with the fix
   removed, because a local server refuses IPv6 instantly instead of black-holing it. It
   now checks which host the tool connects to, and was shown to fail without the fix.
5. **A bug in my own measurement script.** PowerShell variable names are
   case-insensitive; `$procs` overwrote the `$Procs` parameter, `Wait-Process` never
   waited, and the first scaling table was read on timing luck (4 replicas: 367 req/s
   there, 578 in the rerun). Discarded and rerun.
6. **Docker Desktop's engine hung** (HTTP 500 on every call, Kubernetes API unreachable)
   until Docker Desktop was restarted. Nothing about the manifests; recorded because it
   looks like one.

## Limits you should know

- **One node.** Replicas share a machine: this survives a crashed process, not a crashed
  computer. The PodDisruptionBudget is the right shape for several nodes and does little
  here. Topology spread was not used because there is nothing to spread over.
- **No Ingress, no TLS.** The cluster has no ingress controller; installing one means
  applying someone else's manifest, which is a decision for the public-hosting step. Today
  the way in is a local `LoadBalancer` on `localhost:8088`.
- **No autoscaling.** No metrics-server is installed, so `kubectl top` and an
  HorizontalPodAutoscaler do not work. Replica counts here are set by hand.
- **No NetworkPolicy.** Whether Docker Desktop's network would enforce one was not tested,
  so none is claimed.
- **The image comes from the local Docker engine.** The published GHCR image has not been
  pulled by the cluster. That needs an image-pull secret while the package is private, and
  was not tested.
- **`progressDeadlineSeconds` is the default 600 s**, so a stuck rollout is only *marked*
  failed after ten minutes (the old pods keep serving meanwhile; `rollout status` with a
  timeout is the faster signal for automation). It is a one-line change if wanted.
- **No retries, no timeouts configured** in front of the service; the crash drill shows
  why that matters.
- The `restricted` namespace rule was accepted by the manifests but never tested against a
  deliberately violating pod.
- Run-to-run noise in the measurements was not measured.
