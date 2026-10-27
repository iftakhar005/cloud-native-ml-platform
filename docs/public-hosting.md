# Putting it on the public internet, for free, without your laptop

The goal: anyone can open the page and parse an address while your laptop is **switched off**,
at **zero cost**, and with no surprise charges. This document says what each free host really
offers (read from its official documentation on **2026-10-27**), what the model needs, what gets
exposed, how updates and rollbacks work, and exactly what to do. Free tiers change often, so
re-check a page before relying on it.

> **Status: planned and tested, not deployed.** Nothing has been created at any host. Everything that
> can be tested without an account was tested (below). The decisions that need an account, a card or
> your approval are listed under "Decisions that are yours".

## The honest summary

- **No free host I checked meets every requirement at once** (free, no card, no possible charge,
  runs your container, always on). The closest is **Render's free web service**. It is *not* always on:
  it sleeps after 15 idle minutes and the first visitor then waits **one to two minutes**.
- **Zero cost matters more than availability here**, so that trade is the right one. If Render turns out
  to refuse what you need (below), **there is no free option I can honestly recommend that keeps the
  container design**, and I would not suggest a paid plan. The fallbacks are a different design (Vercel
  Hobby, unverified) or keeping the project local with screenshots and a recorded demo.
- **Correction:** an earlier version of this document named Northflank as the primary choice and said
  it needs no card. That was wrong. Its own billing documentation says otherwise (below).

## Hosts compared (official documentation only)

| Host | What the official pages say | Verdict |
|---|---|---|
| **[Render Free](https://render.com/docs/compute-plans)** | Free web service: **0.1 CPU, 512 MB**. [750 free instance hours a month](https://render.com/docs/free); "spins down after 15 minutes without inbound traffic"; waking "takes about one minute"; ephemeral disk; may be restarted at any time. Runs images [from any registry, including GHCR](https://render.com/docs/deploying-an-image). Render's materials also say free instances should not be used for production (seen in search results of its docs, not on the page I fetched) | **Best fit.** Unknowns below |
| Northflank | Sandbox: 2 services, "Always on, no sleeping" ([pricing](https://northflank.com/pricing)). **But** [its billing docs](https://northflank.com/docs/v1/application/billing/project-types) say "All users must add a payment method to create resources, whatever their plan", and the Sandbox "should not be used for production applications". [Billing thresholds are not hard spending limits](https://northflank.com/docs/v1/application/billing/billing-thresholds). No free egress allowance is listed and the pages do not say what happens when free resources run out. Smallest plan is [0.1 vCPU, 256 MiB](https://northflank.com/docs/v1/application/billing/resource-plans-and-quotas) | **Not recommended**: a card is required and the charge risk is unbounded |
| Vercel Hobby | Free; if limits are exceeded you ["wait until 30 days have passed"](https://vercel.com/docs/plans/hobby), not charged; no card mentioned; "non-commercial, personal use only". [FastAPI is supported](https://vercel.com/docs/functions/runtimes/python) (500 MB bundle limit). **Not a container**: it builds from the Git repo | **Fallback, unverified** (see below) |
| Hugging Face Spaces | ["Gradio and Docker Spaces ... require a paid plan to create"](https://huggingface.co/docs/hub/spaces-overview); only static Spaces are free | Out |
| Koyeb | [No free web-service instance](https://www.koyeb.com/pricing) | Out |
| Fly.io | ["New organizations don't have a free tier"](https://docs.fly.io/about/pricing); every organization needs a card | Out |
| Google Cloud Run | ["A Google Cloud billing account is required"](https://docs.cloud.google.com/free/docs/free-cloud-features) for the free tier (card) | Out |
| Railway | [$5 one-time trial for 30 days, then $1 a month](https://docs.railway.com/reference/pricing/free-trial) | Out |
| Oracle Always Free | A VM, not a container platform: [1/8 OCPU and 1 GB](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm); idle VMs "may be reclaimed" (95th-percentile CPU and network under 20% for 7 days, which a quiet demo is); capacity errors; you run Docker, TLS and patching yourself. Card not mentioned on that page | Not recommended |
| Cloudflare quick tunnel | [Free, but "testing and development only"](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), a random URL that dies when you stop it, and it needs your laptop on | Fails the laptop requirement |

### About Render, precisely

**Confirmed in Render's docs:** the free specs above; 750 hours a month (a 31-day month has 744, so one service
fits even if kept awake, and spun-down time does not count); the 15-minute sleep; image-backed web services;
GHCR as a registry (a private image needs a credential, a public one does not); [rollbacks reuse the image tag or
digest](https://render.com/docs/rollbacks); a [deploy hook that accepts `imgURL`](https://render.com/docs/deploy-hooks);
free managed HTTPS on an `onrender.com` URL; and, on charges, that [with no payment method on file, a service
that would incur charges is **disabled instead of billed**](https://render.com/docs/faq).

**Not confirmed, so check at sign-up (and stop if the answer is unwelcome):**
1. **Whether a card is required.** The docs are silent. Render staff say in the [community forum](https://community.render.com/t/use-render-web-service-without-card/23252)
   that a card is *sometimes* requested for verification (a $1 hold that is reversed). Once a payment method is on
   file, the documented charge path is **bandwidth beyond the included amount**. The 1 August 2026 [plan
   change](https://render-www.onrender.com/changelog/updated-plans-for-render-workspaces) officially reduced
   included bandwidth; the "5 GB" figure for free workspaces is from a third-party blog, not checked at source.
2. **Whether the Free instance type is offered for an image-backed service.** Render's pages do not say it is, or
   is not. The service-creation screen will.
3. Whether free rollbacks keep enough history (it says only "a fixed number ... based on your plan"; a rollback
   by digest does not need that history).

## Does the model fit a free host's CPU and memory?

I ran the real image under hard limits (Docker CPU quota, swap off, `--read-only --cap-drop ALL`) on this laptop.
**Memory is not the problem; CPU is.**

| Limit | Ready after* | Parse, one client (median) | Throughput, 4 connections | Peak memory | OOM-killed |
|---|---|---|---|---|---|
| 0.1 CPU, 512 MB (Render Free) | 67 s | 92 ms | 11.1 req/s | 60 MiB | no |
| 0.1 CPU, 256 MiB (Northflank's smallest) | 50 s | 94 ms | 0.8 req/s (an unexplained outlier: 4 timeouts) | 56 MiB | no |
| 0.1 CPU, 128 MB | 128 s | 98 ms | 14.8 req/s | 55 MiB | no |
| 0.1 CPU, 96 MB | 69 s | 97 ms | 9.2 req/s | 54 MiB | no |
| 0.1 CPU, 64 MB | 98 s | 95 ms | 13.7 req/s | 55 MiB | **no** (55 of 64 MiB) |
| reference: 1 CPU, 512 MB | 20 s | 18 ms | 45.5 req/s | 66 MiB | no |

\* *Container creation plus app start, so not purely the app. I could not separate the two: the follow-up
measurement was cut off when the session ended.*

What this means: it **fits comfortably in memory** (even 64 MB), but at 0.1 CPU a parse takes about 95 ms instead
of 18, it serves roughly 9-15 requests a second, and the **cold start is 50-127 seconds**. That is fine for a demo
and nowhere near a capacity claim. Caveats: Docker's CPU-quota emulation on a laptop is *indicative*, not a
promise about Render's scheduler; one run per row; one row is an unexplained outlier.

**Consequence already acted on:** the page used to wait about 100 s for a waking server, shorter than the worst
case measured. It now waits **4 minutes** (60 attempts every 4 s), shows a running "Waited N s" counter, and a
test pins the minimum (3 minutes) so it cannot be shortened by accident.

## What stays local, and what is public

| | Where | Notes |
|---|---|---|
| Kubernetes cluster (Docker Desktop), 3 replicas, rollouts, failure drills | **local only** | for development, testing and demos; untouched by any of this |
| Prometheus, Grafana, alert rules, dashboards | **local only** | never exposed publicly; `/metrics` is hidden on the public service |
| Load tests, `scripts/loadtest.py`, the model-fit tests | local | |
| GitHub Actions, the quality gate, Trivy, GHCR | cloud (GitHub) | already running; no laptop involved |
| **The public service**: one container, the page and the API | **cloud (Render)** | public mode on; no Kubernetes |

**Kubernetes in the cloud is not feasible at zero cost.** Managed control planes are only sometimes free
([Oracle's basic OKE cluster has no control-plane fee](https://www.oracle.com/cloud/cloud-native/kubernetes-engine/pricing);
AKS Free and a GKE credit are reported to, from third-party summaries I did not check at source; EKS has none),
but **worker nodes are always billed** at ordinary VM rates. The only zero-cost compute found above is Oracle's
Always Free VM, which would mean running and securing a cluster yourself on a 1 GB machine that can be reclaimed.
The free hosts above run your container on their own orchestrator, so Kubernetes is not needed for the public
service, and keeping it local for development, tests and demonstrations is the sensible split.

## What gets exposed

| Path | Public? | Why, and what a stranger learns |
|---|---|---|
| `/`, `/assets/*` | yes | the page and its three files |
| `POST /api/v1/parse` | yes | the product. Rate limited, 500 characters at most |
| `POST /api/v1/parse/batch` | yes | at most `THIKANA_MAX_BATCH` (use 10) addresses; counts as one request toward the rate limit |
| `GET /api/v1/model` | yes | model name, a hash identifying the model file, the **git commit** it was built from, and its stated limitations |
| `/healthz`, `/readyz` | yes | the host's health checks need them; `/readyz` also shows the model hash |
| `/metrics` | **no (404)** | request counts and model internals are for your own Prometheus |
| `/docs`, `/redoc`, `/openapi.json` | **no (404)** | smaller surface; the API is documented in `docs/api.md` |
| `X-Thikana-Instance` header | **not sent** | a pod or container name is useful in a cluster and a leak on the internet |

There is **no authentication**: anyone with the URL can use it. What bounds the abuse is the rate limit, the
500-character cap and the free tier's own resource cap, nothing more.

**Secrets.** The image contains none (a test checks the manifests and the workflow for tokens, and the build
allowlist keeps `data/real` and `.env` out). The public host would hold at most two things you must protect:
the **deploy-hook URL** (a secret by Render's own words; it lives in GitHub's encrypted secrets, not in the
repository) and, **only if you keep the GHCR package private**, a `read:packages` token entered at Render.

## What it costs

- **Expected: nothing.** Render's free web service is $0. **Not verified:** the card question above.
- **The one documented way to be charged** is a payment method on file plus bandwidth beyond the included amount.
  A page view is about 22 KB uncompressed and a sample parse answer 431 bytes (both measured), so honest use is
  nowhere near a few GB: a few GB would be on the order of 100,000 page views. A flood
  could be, which is what the rate limit and 500-character cap are for, and why you should **not add a card unless
  you decide to accept that risk**.
- If Render asks for a card at sign-up and you will not provide one: **stop**. Do not substitute a paid plan.
- **Your time:** with the optional deploy job (off by default) an update is automatic; without it, updating is a
  click in Render's dashboard.

## What the visitor's data does

- The app **does not store** what is typed and **never logs** the text, nor the client's address (tests fail if
  either reaches a log line). It logs counts, route, status and duration. The rate limiter keeps client addresses
  **in memory only**, bounded, lost on restart.
- **The host can still see it.** TLS ends at the host's proxy, so the host handles the plaintext and may keep its
  own request logs. This app cannot see or control them, and the page says so.
- **No cookies, no analytics, nothing loaded from other sites** (the CSP forbids it, and a test checks the page loads
  only its own three assets).
- Addresses of real people are personal data. The page asks visitors not to type any and the examples are invented.
  That is a request, not a control.

## Rate limiting

A token bucket per client (a steady rate plus a burst), in memory, per replica, on `/api/*` only (never the page,
`/healthz`, `/readyz` or `/metrics`). It protects one process's CPU from one noisy client. It is **not** DDoS
protection. Behind a proxy every request arrives from the proxy, and the real address is in `X-Forwarded-For`, a
list each proxy **appends** to; anything on the *left* was written by the client and can be forged. So
`THIKANA_TRUSTED_PROXY_HOPS=N` trusts only the Nth entry from the right, and the default `0` ignores the header
(everyone then shares one allowance: annoying, not exploitable). uvicorn's own forwarded-header handling is **off**
in the image (`--no-proxy-headers`): with it on, a forged header bought a fresh allowance, found by
`scripts/check_public.py`. How a given host forwards cannot be known in advance, so measure it (step 4 below).

## How updates and rollbacks work, without your laptop

```
merge to main
  -> GitHub Actions: tests, train, quality gate, build, Trivy scan, publish       (already running)
  -> ghcr.io/iftakhar005/thikana-api:<commit SHA>   and its digest sha256:...    (already running)
  -> optional `deploy` job: POST to Render's deploy hook with imgURL=<that digest> (OFF until you enable it)
  -> Render pulls the digest and starts it
```

Render's [health-check docs](https://render.com/docs/health-checks) describe web services shifting traffic only after
the new instance passes its checks (and cancelling the deploy after 15 minutes if it does not); they do not say whether
that holds on the **Free** type, so do not assume zero downtime on a free instance.

- **Initial setup is manual** (a Render account and service, below). After that, nothing depends on your laptop.
- **Without the deploy job**, update by hand: Render's service page, *Manual Deploy*, or change the image to the
  new digest. Render does not redeploy by itself when a tag moves.
- **Rollback**, two ways, neither needing your laptop: Render's *Deploys > Rollback* (it ["uses the same image tag or
  digest as the target deploy"](https://render.com/docs/rollbacks); doing it in the dashboard turns off autodeploys
  until you re-enable them), or call the hook with an **older digest**, which works as long as that image still exists
  in GHCR.
- The deploy job, its secret handling and how it was tested are in `docs/ci.md`.

## Decisions that are yours

1. **GHCR package: public or private?** *Public* means Render needs no credential, and the image holds no secrets
   and none of `data/real`, but anyone can pull the **code and the model**. *Private* means you give Render a token
   with **only** `read:packages` and a short expiry, entered in Render's own credential form (never pasted into chat
   or committed), and Render then holds it. My preference is public, but it publishes your code.
2. **A card at Render.** If asked, you choose; see "What it costs".
3. **Turning on the deploy job** (a secret and a variable in GitHub). Optional; the service works without it.

## Exact steps (nothing here has been done)

1. Decide the package visibility. For public: GitHub, *Packages*, `thikana-api`, *Package settings*, *Change visibility*.
2. **You create a Render account.** Note whether it asks for a card; if it does and you will not give one, stop.
3. **Create a Web Service from an *Existing Image*** with these values (the labels may differ slightly):

   | Setting | Value |
   |---|---|
   | Image | `ghcr.io/iftakhar005/thikana-api@sha256:<digest>` (copy from the latest `main` run's Summary, "Published") |
   | Instance type | **Free**. If it is not offered for an image, **stop** |
   | Env | `PORT=8000` (Render expects `PORT`, default 10000, to match where the app listens; detection is only "usually" automatic), `THIKANA_PUBLIC_MODE=true`, `THIKANA_RATE_LIMIT_PER_MINUTE=60`, `THIKANA_RATE_LIMIT_BURST=20`, `THIKANA_MAX_BATCH=10`, `THIKANA_TRUSTED_PROXY_HOPS=0` |
   | Health check path | `/readyz` |

4. **Audit it from outside** (allow about two minutes for the first wake), then try the page in a browser:

   ```powershell
   cd E:\My-Projects\cloud-native-ml-platform\.claude\worktrees\devops-portfolio-project-2a4bd1
   python scripts\check_public.py https://<your-service>.onrender.com --probe-rate-limit
   ```

   Every line should say `PASS`; a `FAIL` names exactly what is wrong. For a fair allowance **per visitor**, set
   `THIKANA_TRUSTED_PROXY_HOPS=1`, redeploy and rerun with `--probe-rate-limit`: if *"forging X-Forwarded-For does
   NOT buy a new allowance"* passes, Render really appends the client address and `1` is right; if it fails, set it
   back to `0`.
5. *(Optional)* enable the deploy job: copy the service's deploy hook, add it as the GitHub secret
   `RENDER_DEPLOY_HOOK`, then set the variable `RENDER_DEPLOY_ENABLED` to `true` (`docs/ci.md`).

## If Render does not work out

- **Free instance not offered for images, or a card is demanded that you will not provide:** there is no free host
  above that keeps the container design. **Vercel Hobby** is the one card-free alternative found, but it is a
  *different design*: Vercel builds from the Git repo rather than running your image (so the GHCR workflow does not
  apply), the model file is gitignored and would have to be committed or built in the Vercel build, `python-crfsuite`'s
  native wheel is unchecked on its runtime, serverless cold starts differ, and Hobby is "non-commercial, personal use
  only". Worth a small spike only if you want it; it is **not verified** to run this model.
- **Otherwise** keep it local, with screenshots and a recorded demo of the page and the cluster.

## What was verified, and what was not

**Verified on this machine** (the real image, `--read-only --cap-drop ALL`; a real browser): the page and its assets
are served with correct types and a strict CSP; public mode hides `/metrics`, `/docs`, `/openapi.json` and the
instance name; the rate limiter returns 429 with `Retry-After`, never limits the page or probes, and a forged header
cannot bypass it; the page renders results in English, Bangla and with an emoji before the address, shows the right
message for empty, too-long, rate-limited, server-gone and server-waking input, treats hostile text as text, makes
zero requests to other origins and has no horizontal scroll at phone width; the highlight offsets match real API
output; the wake-up wait is 4 minutes (browser-checked with a stub that fails three times, then answers);
`scripts/check_public.py` passes a correct service (21 of 21 checks against the real container) and fails each way a
deployment can be wrong; the model fits in 64 MB; the deploy job's script was **executed** against a fake Render
server (15 tests). Each protection was broken on purpose and a test failed, about 40 distinct times in all.

**Not verified:**
- **Anything at a real host:** that the account, service, image pull, port and health check work; Render's real cold
  start (my 50-127 s is a laptop's CPU quota, not Render's scheduler); the card question; the free image-backed
  instance; the bandwidth allowance; rollback history on the free tier; how Render forwards client addresses.
- **The deploy job against real Render**, and **`actionlint` on the final workflow** (Docker was stopped).
- Browsers other than Chromium, and screen readers.
- Billing behaviour beyond what the documentation states, for any host.

## Turning it off

Delete the service in Render's dashboard; delete any pull token on GitHub (Settings, Developer settings, Tokens);
set the package back to private if you made it public; set `RENDER_DEPLOY_ENABLED` to anything but `true`.
