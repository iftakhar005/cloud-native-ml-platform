# CI: GitHub Actions

`.github/workflows/ci.yml` turns a push into a **tested, scanned, SHA-tagged image in
GitHub's container registry (GHCR)**. It does not deploy anything; see "What it does not
do".

```
verify  (read-only token)                     image  (the only job that can write packages)
  install -> pytest -> train_all -> gate  -->   build -> smoke test -> Trivy report -> Trivy gate -> push
                          model must pass        |                                                    |
                          the quality gate       runs as Kubernetes will                        main only, never a PR
                                                 (non-root, read-only, no caps)
```

| When | What runs |
|---|---|
| pull request | everything **except** the push. The registry is never touched |
| push to `main` | everything, then `ghcr.io/<owner>/thikana-api:<full-git-sha>` is pushed |
| manual (`workflow_dispatch`) | same as a PR (no push, because the ref is checked) |

The image is tagged with the **full 40-character commit SHA** and nothing else. There is
no `latest`: a moving tag cannot answer "which code is running?". The same SHA is baked
into the image, so `GET /api/v1/model` reports it and a running container can be traced to
a commit.

## Secrets, tokens and permissions (how it works)

**No secret is stored in this repository, and none is needed.** The workflow uses only
`GITHUB_TOKEN`, which GitHub creates for each run and revokes when the run ends.

- **What it can do is set by `permissions:` in the file.** The default for the whole
  workflow is `contents: read`. Only the `image` job adds `packages: write`, which is what
  allows a push to `ghcr.io/<owner>/...`. The `verify` job, which runs `pip install` and
  the test suite (third-party code), keeps the read-only token.
- **It is handed to one step.** The publish step receives it as an environment variable and
  passes it to `docker login --password-stdin`. It is never on a command line (visible in
  process lists), and no earlier step sees it.
- **Pull requests cannot publish** (the step is guarded) and a PR from a fork gets a
  read-only token regardless. The workflow does **not** use `pull_request_target`, which
  would run fork code with write access.
- **Why the package can be pushed at all:** the build adds the label
  `org.opencontainers.image.source`, which links the package to this repository, and
  GitHub then lets this repository's `GITHUB_TOKEN` write it.
- If you ever need a real secret (a cloud key, a Slack webhook), it goes in
  *Settings > Secrets and variables > Actions*, is referenced as `${{ secrets.NAME }}`,
  and is never echoed or written to a file. A test fails if the workflow references any
  secret other than `GITHUB_TOKEN`, so adding one is a deliberate, reviewed change.
- **Do not paste a personal access token into the repo, an issue or a chat.** If one ever
  lands in git history, deleting the file does not help: revoke the token.

## Supply chain: what is pinned and why

A workflow runs other people's code with your token. So:

- **Every action is pinned to a full commit SHA**, with the release in a comment
  (`# v7.0.1`). A tag can be moved; a commit cannot.
- **The scanner is the Trivy container image pinned by digest, not `trivy-action`.** In
  March 2026 an attacker force-pushed almost every version tag of
  `aquasecurity/trivy-action` (and `setup-trivy`) to malicious commits, so anyone using a
  tag ran the attacker's code. Sources:
  [The Hacker News](https://thehackernews.com/2026/03/trivy-security-scanner-github-actions.html),
  [Aqua's own account](https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know),
  [Legit Security](https://legitsecurity.com/blog/the-trivy-supply-chain-compromise-what-happened-and-playbooks-to-respond).
  The image digest used here is the exact one the findings below were produced with.
- The Docker base image is pinned by digest (see `docs/docker.md`).

Pinning is not a one-off: pins go stale. Updating one is a visible commit (look the new
SHA up with `git ls-remote --tags https://github.com/<owner>/<repo>`).

## The quality gate

CI retrains the model, so the published image holds a file nobody has looked at. The gate
(`python -m thikana.training.gate`) scores it on five hand-written sets (v1-v4 and the fresh village set v6) and fails the
job if any score is under its floor (v1 0.970, v2 0.920, v3 0.900, v4 0.920, v6 0.950).

Why behaviour and not a hash: **the Linux-trained model is not byte-identical to the
Windows-trained one.** Measured, same code and data (on the model BEFORE the village fix of
decision D12; the new model, `crf_all_district_memory_vocab` trained on 8,000 examples, has not been
compared across platforms, so the first CI run after that change is its first cross-platform check, and
the floors leave a margin for exactly that):

| | SHA-256 of `.crfsuite` | predictions on 278 hand-written addresses |
|---|---|---|
| trained on Windows | `f92116ba...` | reference |
| trained on Linux | `ef16cc1e...` | **278 of 278 identical**, v4 F1 0.8972 for both |

The likely cause is last-bit floating-point differences in a native library across
platforms; that is a guess, not something I traced. Consequence: the published image's
`model_version` differs from your local one.

What the gate is **not**: v1-v4 are not real data and were each scored once to choose
between models. A pass means "this is the model we measured", never "this model works on
real addresses". The floors are the observed score minus a margin, not a target.

## What Trivy found (2026-10-27, Trivy 0.76.1)

On the image built from commit `d286528` (base `python:3.12-slim`, Debian 13.7):

| severity | total | with a fix available |
|---|---|---|
| CRITICAL | 0 | 0 |
| HIGH | 44 | **0** |
| MEDIUM | 63 | 5 |
| LOW | 62 | 1 |
| UNKNOWN | 1 | 0 |

- **The 16 packages this project installs have no findings.**
- All 44 HIGH are Debian system libraries (util-linux, ncurses, systemd, acl, perl-base),
  and Debian has published no fix for any of them.
- The 6 findings in Python packages are all the base image's own `pip 25.0.1`
  (5 MEDIUM, 1 LOW), which the service never runs. Removing pip from the runtime stage
  would clear them; that is not done yet and is a reasonable next hardening step.

**The gate:** fail on HIGH or CRITICAL that **have a fix available** (`--ignore-unfixed`).
Run strictly, the same image fails (44 HIGH), so the gate can fail; it was run both ways.
The trade-off, plainly: unfixed findings do not block a build, because nothing in this
project can remove them. They are listed in every run's summary, and the moment Debian
ships a fix the gate starts failing, which is the signal to pull a newer base image. A
scan is a snapshot: a new CVE next week is invisible to this run.

## What was verified, and what was not

**Verified, on this machine:**

- `actionlint` 1.7.12 (with shellcheck on every `run:` block) is clean, and was shown to
  report a seeded bug.
- The `image` job's shell steps (name, build, smoke test, export, report, gate) were
  **executed** from the workflow file against a clean checkout of the commit with the
  Linux-trained model: all exit 0, and the findings table matched a separate Trivy run.
  One deliberate difference: the smoke test used host port 18000 because 8000 was already
  taken on this laptop.
- The smoke test was shown to fail when the baked-in SHA does not match, and the Trivy
  gate to fail when run strictly.
- The `verify` steps ran in a clean `python:3.12-slim` Linux container: dependencies
  install from `requirements/dev.txt`, 165 tests pass, `train_all` succeeds.
- `tests/test_ci_workflow.py` (19 tests) guards pins, permissions, step order and the
  publish conditions; nine different deliberate breakages each made it fail.

**Verified on GitHub:** the first run, on the pull request, finished with both jobs green
(reported by the project owner from the Checks tab; the log was not shared with me, so
this file does not quote timings or counts from it). That covers the real actions
(`checkout`, `setup-python`, `upload/download-artifact`), the pip cache, the quality gate
and the image build, smoke test and Trivy gate on a hosted runner.

**Verified on GitHub, push to `main`** (merge commit `bdd418c`, run `ci #3`, green, 2m 14s
on the Actions list; the run's summary page was shared with me):

- **The publish path works.** `docker login ghcr.io` and `docker push` with the built-in
  `GITHUB_TOKEN` succeeded, and the summary records
  `ghcr.io/iftakhar005/thikana-api:bdd418c1e6af72776d86755085b17cf388a80b3a`, digest
  `sha256:8123789f1e3f1a24028a98a9a957eb838702950b1bfe1dc9ad4435b28b605891`.
- **The Trivy numbers on the runner equal the local ones** in every cell of the table above
  (0 / 44 / 63 / 62 / 1 by severity; 0 / 0 / 5 / 1 / 0 fixable), on a different day and
  machine. They will drift as the vulnerability database changes.

**Verified by pulling it** (merge commit `f18f777`, digest
`sha256:b3e619c005252f12b3514e7bcb0dff80d7f988b3476b05db6c45bdf3c80f15c8`; details in
`docs/kubernetes.md`):

- **The package is private.** A cluster with no credential got `unauthorized` from the
  registry. (The package page itself was never looked at; this is observed behaviour.)
- **The published image runs.** With a `read:packages`-only pull secret, three pods pulled
  it, their `imageID` equalled the digest from the CI log, and `/api/v1/model` reported
  the full commit SHA `f18f777a3c...`. The model inside has version `14f57233ee3e`, not the
  local `49b58b49a6fe`: the Linux-trained file, as described above.

**Not verified:** that the digest of an image that does not exist is distinguishable from
a private one (GHCR answers `unauthorized` to both), so the pull *with* a credential is the
only real proof, and it was done once.

## The optional `deploy` job (off by default)

For a **cloud** host (Render's free tier, `docs/public-hosting.md`) the workflow has a third job
that tells the host to run the image just published. **It does nothing unless you turn it on**,
and it was written and tested, not run against a real host.

| | |
|---|---|
| When it runs | only for a push to `main`, after the `image` job succeeded, **and** the repository *variable* `RENDER_DEPLOY_ENABLED` is exactly `true` |
| What it does | one `curl` POST to Render's deploy hook with `imgURL=` set to the **digest** CI just pushed (`ghcr.io/<owner>/thikana-api@sha256:...`) |
| What it can read | nothing from GitHub: `permissions: {}`, no checkout, and **no third-party action**, so no action can ever see the secret |
| What it never does | print the hook URL (it reports an HTTP status only), deploy a tag, or deploy anything that is not a `ghcr.io` digest |

**Secret versus variable, and why both.** The hook URL is a *secret*: Render says "Your deploy hook URL is a
secret!", because anyone holding it can trigger a deploy of that service (only of images with the same
name, so the damage is limited, but keep it private). It goes in *Settings > Secrets and variables >
Actions > Secrets* as `RENDER_DEPLOY_HOOK`. The on/off switch is an ordinary *variable*,
`RENDER_DEPLOY_ENABLED`, because it is not sensitive and you want to be able to read and flip it. If the
hook ever leaks, use *Regenerate Hook* in Render and replace the GitHub secret.

**To enable:** create the Render service first, copy its deploy hook, add the secret, then set the variable to
`true`. **To disable:** set the variable to anything else (or delete it). **Rollback** needs no CI: Render's
*Deploys > Rollback*, or the same hook called by hand with an older digest as `imgURL`.

**How it was tested:** the exact text of the job's script is executed by `tests/test_deploy_job.py` against a
fake Render server (15 tests: method, encoding, the hook's own `?key=` kept, 200 and 202 accepted, every other
status fails the job, five kinds of bad image refused without calling Render, the secret never printed), and
`tests/test_ci_workflow.py` pins the gating, the missing permissions and the absence of third-party actions;
14 deliberate breakages were each caught. **Not done:** `actionlint` was not run on this version (Docker was
stopped when it was written), and it has not run on GitHub, so expect to read its first real run closely.

## What it does not do

- **By default it does not deploy.** A GitHub-hosted runner cannot reach a cluster on your laptop, so nothing
  here deploys to it. The optional job above targets a cloud host and is off until you enable it.
- No image signing, SBOM or build provenance; no scheduled re-scan; no automated update of
  pinned versions. All are reasonable extensions, none is claimed.
- It scans for known vulnerabilities only. It says nothing about whether the model is
  right.

## First run: what to do (all three steps are done)

1. Push the branch and open a pull request into `main`. The `verify` and `image` jobs run;
   nothing is published.
2. Fix whatever the first run shows (see the table below), push again.
3. Merge to `main`. The same jobs run and the SHA-tagged image is pushed. A new GHCR
   package is **private** by default; making it public is a deliberate click in the
   package's settings, not something the pipeline does.

## Run the same checks locally

```powershell
cd E:\My-Projects\cloud-native-ml-platform\.claude\worktrees\devops-portfolio-project-2a4bd1
.\.venv\Scripts\Activate.ps1
python -m pytest -q
python -m thikana.training.train_all
python -m thikana.training.gate
```

Then build and scan as in `docs/docker.md`; the scan is
`docker run --rm -v "${PWD}:/work" aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c image --input /work/image.tar --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`
after `docker save <image> -o image.tar`.

## When it goes red

| Symptom | Likely cause |
|---|---|
| `verify` fails at "Quality gate" | A model change lowered a score. Read the printed per-set F1. Do **not** lower a floor to get green; decide whether the change is wanted |
| `image` fails at the Trivy gate | A HIGH/CRITICAL now has a fix. Usually: pull a newer base image (`docs/docker.md`, "Updating the base image"), rebuild, re-scan |
| `image` fails at "Smoke test" | The image builds but does not run as the app user, or the baked SHA is wrong. The step prints the container log |
| Publish fails with `denied` / `403` | Workflow permissions on the repository forbid package writes (Settings > Actions > General), or an existing package of that name is not linked to this repo |
| A pinned action disappears | Pinned SHAs stay available unless the repository is deleted; look for the replacement and re-pin |
