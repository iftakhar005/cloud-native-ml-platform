# Putting it on the public internet

A small web page and the API, served by the same container, on a free host. This document
says what that exposes, what it costs, what was verified and what was **not**, and how to do
it. Facts about hosts were read from their official pages on **2026-10-27**; free tiers change,
so re-check before relying on any of them.

> **Status: prepared and tested, not deployed.** Creating the hosting account and the service
> is a step only you can do. Everything that can be tested without an account was tested
> (below). The deployment itself, the host's real limits and how its proxy forwards client
> addresses are **unverified** until you run `scripts/check_public.py` against the live URL.

## What was built

- **A page** at `/` (`thikana/web`, four static files, no framework, no build step). Highlights
  the parts of an address with a colour **and** a text label, shows the model's own limitations
  from the live API, and tells the visitor not to type real people's addresses.
- **Public mode** (`THIKANA_PUBLIC_MODE=true`): `/metrics`, `/docs`, `/redoc` and `/openapi.json`
  return 404 and the pod/host name header is not sent. The cluster leaves it off.
- **A per-client rate limit** on `/api/*` (`THIKANA_RATE_LIMIT_PER_MINUTE`), with a bounded client
  table, `Retry-After`, and safe handling of `X-Forwarded-For` (see "Rate limiting" below).
- **Security headers** on every response, and a strict Content-Security-Policy on the page: it can
  load scripts and styles from itself only, connect to itself only, and cannot be framed.
- **`scripts/check_public.py`**: audits a deployed URL from the outside.
- **CI** now runs the image in public mode before publishing it and fails if `/metrics` is
  reachable or the instance name leaks.

## Which free host (and what the official pages actually say)

| Host | What the official page says | Verdict |
|---|---|---|
| [Hugging Face Spaces](https://huggingface.co/docs/hub/spaces-overview) | "Gradio and Docker Spaces run on compute and require a paid plan to create"; only *static* Spaces are free | **Not usable** for the API |
| [Koyeb](https://www.koyeb.com/pricing) | no free web-service instance listed (only a 5-hour Postgres) | **Not usable** |
| [Northflank](https://northflank.com/pricing) | free *Sandbox*: "2 services", "No card needed", "Always on, no sleeping", "Up to $20/mo of resources on Northflank Cloud", external-registry images included | **Primary choice** |
| [Render](https://render.com/docs/free) | free web service: 750 instance hours a month, spins down after 15 minutes without traffic, "about one minute" to wake, ephemeral disk; images can be deployed from a registry ([docs](https://render.com/docs/deploying-an-image)) | **Alternative** |
| [Cloudflare quick tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) | free, no account, but "for testing and development only", no uptime guarantee, a random URL that dies when you stop it | a demo from the laptop, **not** a host |
| Fly.io, Google Cloud Run | reported (by third-party summaries, not checked at source) to need a payment card | out for "no card" |

**Not confirmed from the official pages** (so check them when you sign up, and stop if the answer is
unwelcome): Northflank's exact free RAM and CPU (only the $20/month budget is stated); whether GHCR
is named among the supported registries (external registries are); Render's payment-method
requirement, its free RAM/CPU figures, its bandwidth allowance, and whether a *free* instance may
be image-backed (the pages are silent on each).

## What gets exposed

| Path | Public? | Why, and what a stranger learns |
|---|---|---|
| `/`, `/assets/*` | yes | the page and its three files |
| `POST /api/v1/parse` | yes | the product. Rate limited, 500 characters at most |
| `POST /api/v1/parse/batch` | yes | at most `THIKANA_MAX_BATCH` (use 10) addresses; same rate limit counts it as one request |
| `GET /api/v1/model` | yes | model name, a hash that identifies the model file, the **git commit** it was built from, and its stated limitations |
| `/healthz`, `/readyz` | yes | the host's health checks need them; `/readyz` also shows the model hash |
| `/metrics` | **no (404)** | request counts and model internals are for your own Prometheus |
| `/docs`, `/redoc`, `/openapi.json` | **no (404)** | smaller surface; the API is documented in `docs/api.md` |
| `X-Thikana-Instance` header | **not sent** | a pod or container name is useful in a cluster and a leak on the internet |

There is **no authentication**: anyone with the URL can use it. What bounds the abuse is the rate
limit, the 500-character cap and the free tier's own resource cap, nothing more.

## What it costs

- **Expected: nothing.** Northflank states a free plan that needs no card. **I could not verify the
  billing behaviour** beyond that page. If you ever add a payment card, usage above the free
  allowance could be charged: do not add one unless you mean to.
- **Render** (if you use it instead): the free tier suspends the service rather than charging when
  the monthly hours run out, but the docs say a workspace *without* a payment method has all free
  services suspended for the rest of the month if the included bandwidth runs out, and the
  allowance is not stated on the page I read.
- **GitHub**: the pipeline and GHCR are already in use. A *private* package needs a pull credential
  at the host (below); a *public* one does not.
- **Your time**: nothing here updates itself. CI publishes a new image per merge, but telling the
  host to use it is manual, because automating that needs a deploy credential stored in GitHub, a
  secret and a decision this document does not make for you.

## What the visitor's data does

- The app **does not store** what is typed and **never logs** the text, nor the client's address
  (pinned by tests: they fail if either reaches a log line). It logs counts, route, status and
  duration. The rate limiter keeps client addresses **in memory only**, bounded, and loses them on
  restart.
- **The host can still see it.** TLS ends at the host's proxy, so the host handles the plaintext
  and may keep its own request logs. This app cannot see or control them. The page says so.
- **No cookies, no analytics, nothing loaded from other sites** (the CSP forbids it, and a test
  checks the page loads only its own three assets).
- Addresses of real people are personal data. The page asks visitors not to type any, and the
  examples are invented. That is a request, not a control: there is no way to stop someone typing
  one.

## Rate limiting: what it does and does not do

It protects the CPU of one process from one noisy client: a token bucket per client (a steady rate
plus a burst), in memory, per replica. It is **not** DDoS protection; a flood that saturates the
host's network is the host's problem.

The hard part is *who the client is*. Behind a proxy, every request arrives from the proxy, and the
real address is in `X-Forwarded-For`, a list each proxy **appends** to. Anything on the *left* was
written by the client and can be forged. So `THIKANA_TRUSTED_PROXY_HOPS=N` trusts only the Nth entry
from the right, and the default `0` ignores the header entirely. Behind a proxy `0` means everyone
shares one bucket: annoying, not exploitable, so it is the safe way to be wrong.

**Found by testing, not reasoning:** uvicorn has its *own* forwarded-header handling, on by default,
which trusts `X-Forwarded-For` from any peer on `127.0.0.1` and rewrites the client address before
the app sees it. With it on, a forged header bought a fresh allowance even at `0` hops. The image now
starts uvicorn with `--no-proxy-headers` (pinned by a test), so exactly one mechanism decides.

How a given host forwards cannot be known in advance. Find out with the audit script (below).

## Deploy (Northflank, the primary choice)

I have not driven Northflank's interface, so treat the labels as approximate and the *values* as the
point.

1. **Merge this branch.** CI builds, scans and publishes `ghcr.io/iftakhar005/thikana-api:<full
   commit SHA>`. From that run's **Summary** page ("Published") copy the line
   `ghcr.io/iftakhar005/thikana-api@sha256:...`. Deploy that **digest**.
2. **Let the host pull it.** The package is private, so choose one:
   - **Make the package public** (GitHub: Packages, `thikana-api`, Package settings, Change
     visibility). Then no credential leaves GitHub. Anyone can then pull the image: it contains the
     model and the serving code, no secrets and none of `data/real`.
   - **Keep it private** and give Northflank a pull credential: a classic token with **only**
     `read:packages`, a short expiry, entered in Northflank's own registry-credential form (never
     pasted into chat or committed). Northflank then holds that token; delete it when you are done.
3. **Create the service** from an external image with these values:

   | Setting | Value |
   |---|---|
   | Image | `ghcr.io/iftakhar005/thikana-api@sha256:<digest>` |
   | Port | `8000`, protocol HTTP, **public** |
   | Resources | the smallest the free plan offers (the process used about 43-52 MiB in the earlier tests) |
   | Health checks | readiness `GET /readyz`, liveness `GET /healthz` |
   | Env | `THIKANA_PUBLIC_MODE=true`, `THIKANA_RATE_LIMIT_PER_MINUTE=60`, `THIKANA_RATE_LIMIT_BURST=20`, `THIKANA_MAX_BATCH=10`, `THIKANA_TRUSTED_PROXY_HOPS=0` |

4. **Audit it from outside**, using the URL the host gives you (it should be https):

   ```powershell
   cd E:\My-Projects\cloud-native-ml-platform\.claude\worktrees\devops-portfolio-project-2a4bd1
   python scripts\check_public.py https://<your-service-url> --probe-rate-limit
   ```

   Every line should say `PASS`. A `FAIL` names exactly what is wrong. Then open the URL in a
   browser and try the examples.
5. **Optionally, fair per-visitor limits.** With `0` hops everyone shares one allowance. To give
   each visitor their own, set `THIKANA_TRUSTED_PROXY_HOPS=1`, redeploy and rerun the audit with
   `--probe-rate-limit`. If *"forging X-Forwarded-For does NOT buy a new allowance"* passes, the
   host really does append the client address and `1` is right. If it fails, set it back to `0`.

**Capacity, honestly:** one full CPU core served about 148 requests per second in the earlier laptop
test (32 connections; one run, noise not measured). A free plan with a fraction of a core serves a
fraction of that. That is plenty for a demo and not a capacity claim for anything else.

### If you use Render instead

Create a Web Service from an *Existing Image* with the same image, port and environment variables,
and choose the Free instance type **if it is offered for an image-backed service** (the docs do not
say). Expect to wait about a minute for the first request after 15 idle minutes: the page already
copes with that, showing "Waking the server" and retrying for about 100 seconds. Render does not
redeploy when a tag moves; a digest is the safer reference.

## What was verified, and what was not

**Verified (on this machine, against the real Docker image run with `--read-only --cap-drop ALL`):**
the page and its assets are served with correct MIME types and a strict CSP; public mode hides
`/metrics`, `/docs`, `/openapi.json` and the instance name; the rate limiter returns 429 with
`Retry-After`, never limits the page or probes, and cannot be bypassed by a forged header; the page
renders results (English, Bangla, an emoji before the address), shows the right messages for empty,
too-long, rate-limited, server-gone and server-waking cases, treats hostile text as text (0 elements
injected), makes 0 requests to other origins, and has no horizontal scroll at phone width in light
mode; the highlight offsets match real API output; `scripts/check_public.py` passes a correct
service and fails each way a deployment can be wrong; each protection was broken on purpose and a
test failed (about 20 distinct breakages: 12 in the server, 6 in the page logic, 1 in the CI smoke
step and 3 in the audit script).

**Not verified:**
- **The deployment itself**, the host's real CPU/RAM/bandwidth limits, and its billing behaviour.
- **How the host's proxy writes `X-Forwarded-For`** (so the right hop count is unknown until audited).
- **TLS** (the host's certificate); the audit script validates it when you run it, I did not.
- Real-browser behaviour beyond the one browser used here (Chromium-based), and screen readers.
  The page uses labels, live regions and visible focus, but was not tested with assistive technology.
- Dark mode was seen on the desktop layout and light mode on the phone layout, not every combination.
- That the CI smoke step behaves on GitHub's runner exactly as it did here.

## Turning it off

Delete the service in the host's dashboard, then delete any pull token (GitHub: Settings, Developer
settings, Tokens) and, if you made the package public for this, set it back to private.
