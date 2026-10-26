# Docker

The API as a container image. Everything below was run and measured, not assumed.

## Build and run

Run these in PowerShell from the folder that contains the `Dockerfile` (in this
session's setup that is the git *worktree* folder, not the empty main checkout).

```powershell
# 1. The model is gitignored, so it must exist locally before the image can contain it.
python -m thikana.training.train_all

# 2. Build. The tag carries the git commit; --dirty marks uncommitted changes to tracked files.
$sha = git describe --always --dirty
docker build -t thikana-api:$sha -t thikana-api:latest --build-arg GIT_SHA=$sha .

# 3. Run
docker run --rm -p 8000:8000 thikana-api:latest
```

Then open <http://localhost:8000/docs>. The container's own log is one JSON line per request.

The strictest way to run it (the service needs none of these privileges, and this is
verified, so Kubernetes can enforce the same):

```powershell
docker run --rm -p 8000:8000 --read-only --cap-drop ALL --security-opt no-new-privileges thikana-api:latest
```

Configuration is the same `THIKANA_*` environment variables as `docs/api.md`, passed
with `-e NAME=value` or `--env-file`.

## What is in the image

| | |
|---|---|
| Base | `python:3.12-slim`, **pinned by digest** (Python 3.12.15, Debian 13) |
| Packages | the 16 in `requirements/serve.txt`; no numpy, pandas or pytest |
| Code | `thikana/api` plus `schema`, `text`, `features`, `model`; **not** `thikana/training` |
| Model | `crf_all_district_memory` and its sidecar, **baked in** |
| User | uid 10001 `app`, no home, no login shell. Code and model are root-owned and read-only |
| Process | one `uvicorn`, PID 1, exec-form `CMD`, so `SIGTERM` reaches it directly |
| Health | `HEALTHCHECK` calls `/readyz` (ready means *a model is loaded*) |

Model version, image tag and git commit travel together: `GET /api/v1/model` reports
the model's SHA-256 prefix and the baked-in git SHA. Verified: the hash inside the
container (`49b58b49a6fe`) equals the hash of the same files on the host. Rolling the
model back is running the previous image.

## Measured

All sizes are `docker image ls` (unpacked) so the comparison is like for like.

| | Tutorial-style | This project |
|---|---|---|
| Image size | 535 MB | **200 MB** (63% smaller) |
| Added on top of the 177 MB base | 358 MB | **23 MB** |
| Build context | 4.3 MB | **496 kB** |
| Packages | 31 (pandas, numpy, pytest, ...) | 16 |
| Runs as | root | uid 10001 |
| Contains | tests, 14 training files, all 16 model files, `data/` (including `data/real/addresses_raw.csv`) | 2 model files, serving code only |

"Tutorial-style" is a single stage, the full dev requirements, `COPY . .`, on the same
slim base, built only for this comparison (not in the repo). A full `python:3.12` base
would be larger still; it was not pulled. Sizes will drift as dependencies update.

A running replica at idle: **42.6 MiB**, 2 processes, 0.25% CPU. That sizes the
Kubernetes requests and limits (to be re-measured under load).

## Why it is built this way

- **Multi-stage.** Stage 1 installs the pinned packages into a virtualenv; stage 2 copies
  *only that environment* onto a clean base. No pip cache or build tooling ships.
- **`--only-binary=:all:`** in a compiler-free builder: a dependency that would need
  compiling fails the build loudly instead of silently slowing it.
- **Allowlist `.dockerignore`.** Ignore everything, then permit what is needed. A new file
  is out of the image until someone lets it in. This is what keeps `.venv`, `.git`, `.env`
  and `data/real/` (personal addresses) out of every image and every registry.
- **Layer order = least to most frequently changing** (dependencies, model, core modules,
  API code). Changing one line of API code rebuilds exactly one small layer and reuses
  the 17-21 second `pip install`. Measured: before reordering, a code edit also rebuilt
  the model layer.
- **Base pinned by digest.** A tag can be re-pointed; a digest cannot. Updating the base
  is therefore a visible commit (see below).

## Failure modes, as run

| Situation | What happens |
|---|---|
| Model file missing or corrupt | Container stays up. `/healthz` 200, `/readyz` and parse 503, Docker health becomes `unhealthy`, one log line with the error type and location. No restart loop |
| Bad configuration (`THIKANA_MAX_TEXT_CHARS=lots`) | Exits at once with code 1 and `THIKANA_MAX_TEXT_CHARS must be an integer, got 'lots'` |
| `docker stop` | Graceful: about 1.6 s, exit code 0 |
| Running read-only, all capabilities dropped | Starts and parses normally |
| App user writing to `/app`, `/opt/venv` | Permission denied (writes to `/tmp` work) |

## Bugs this process found (kept here because they teach)

1. **Directories without the execute bit.** `COPY --chmod=0644` applies to directories
   too, and a directory without `x` cannot be entered by anyone but root. The image built
   and looked fine, then crashed as the non-root user with
   `No module named 'thikana.api'`. Fixed with `--chmod=a=rX`. Only running as the real
   user finds this.
2. **A wrong claim in my own comment.** I wrote that removing pip left "no package
   installer"; the base image still ships its own system pip, `apt-get` and a shell. The
   comment now says what is true. What actually protects the container is the
   unprivileged user, root-owned read-only code, and no capabilities.
3. **Looking too early.** An empty `docker logs` right after `docker run` meant "has not
   crashed yet", not "silent". Wait for the container, then read its log.

## Limits you should know

- **Vulnerabilities:** scanned with Trivy; results and the gate policy are in
  `docs/ci.md`. The short version: no findings in the 16 packages this project installs;
  44 HIGH findings, none with a fix available, all in the Debian base image.
- **The base image is not minimal.** It has a shell, `apt` and `pip`. A distroless base
  would remove them, at the cost of debuggability, and the `python-crfsuite` wheel is
  built for glibc so Alpine is not an option.
- **`latest` is a convenience tag.** Anything that must be reproducible should use the
  git-sha tag.
- **The model is not in git.** `models/` is gitignored, so CI must run `train_all` before
  `docker build`. Retraining on the *same machine* produced byte-identical files, but
  **Windows and Linux do not**: the Linux-trained `.crfsuite` has a different SHA-256 (so
  a different `model_version`) while giving identical predictions on all 278 hand-written
  addresses. The image CI publishes therefore contains a different file from your local
  one; `docs/ci.md` explains how that is checked.
- **Updating the base image:** `docker pull python:3.12-slim`, read the new digest with
  `docker image inspect python:3.12-slim --format "{{index .RepoDigests 0}}"`, edit the
  `ARG PYTHON_IMAGE` line, rebuild, and run the tests.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `error getting credentials ... docker-credential-desktop not found in %PATH%` during `docker build` | Seen when building from **Git Bash**. The build plugin cannot find Docker Desktop's credential helper. Build from PowerShell (the same command works there), or add `C:\Program Files\Docker\Docker\resources\bin` to `PATH`. Not a Dockerfile problem |
| `curl` returns nothing right after `docker run -d` | The container is still starting and Docker's port proxy accepts then drops the connection. Retry with `curl --retry 30 --retry-delay 1 --retry-all-errors` (plain `--retry-connrefused` does not retry an empty reply) |
| `COPY failed: file not found ... models/crf_all_district_memory.crfsuite` | The model is gitignored. Run `python -m thikana.training.train_all` first |
| Container exits at once with `ModuleNotFoundError` | A file the code imports is missing from the `.dockerignore` allowlist or from a `COPY`. `tests/test_docker_files.py` checks the two agree |
| Port already in use | Another container has the port. Use `-p 8800:8000` and browse to 8800 |

Static checks on the Dockerfile and `.dockerignore` run in the normal test suite
(`tests/test_docker_files.py`) and need no Docker. Each was shown to fail when its
guarantee is deliberately broken (`COPY . .`, no `USER`, an unpinned base, shipping the
training code, a shell-form `CMD`, a wrong layer order).
