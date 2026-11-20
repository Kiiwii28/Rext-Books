# Render deployment experiment

A throwaway deployment of Rextbooks **exactly as it is**, used to answer one
question: *does the app's full functionality — including PDF/EPUB export via
headless Chromium — fit on Render's free 512 MB instance?*

Nothing in the application code changes for this. It is deployment
configuration plus one Dockerfile, and `app.py`, the templates and the static
files are the same ones used locally.

> **Not the stateless version.** In this deployment books, settings and keys
> live inside the container's filesystem, which Render wipes on every restart,
> redeploy or spin-down. That is expected here: this exists to measure memory
> use and export reliability, not to hold real work. Use it with throwaway
> books only.
>
> **Your books do come back, though.** The browser keeps its own copy of every
> book it has opened (`static/js/local-store.js` → IndexedDB) and re-uploads
> anything the server has lost on the next page load, so a redeploy no longer
> destroys work on the machine you edited from. Two caveats: the copy is
> per-browser (a different device or cleared site data has nothing to restore),
> and uploaded image files under `books/assets/` are not mirrored — books built
> from Wikimedia/Pexels images are fine, local uploads may need re-adding. If
> you need server-side durability across devices, that means a persistent disk
> (paid plan) or the stateless/BYOK variant, not this deployment.

---

## 1. Get the code onto GitHub

Render deploys from a Git repository, not from your machine.

1. Create an empty repository on GitHub (private is fine).
2. From the project folder:
   ```bash
   git init                      # if it isn't a repo yet
   git add .
   git commit -m "Rextbooks"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
3. Confirm `experiments/render/Dockerfile` and `.dockerignore` are in the repo,
   and that `books/`, `local_settings.json` and `.env` are **not** (they are
   gitignored already).

---

## 2. Create the service in the Render dashboard

**New +** → **Web Service** → connect the repository, then fill in:

| Field | Value |
| --- | --- |
| Name | `rextbooks-test` (anything) |
| Region | whichever is nearest to you |
| Branch | `main` |
| **Root Directory** | **leave blank** (repository root) |
| Language / Runtime | **Docker** |
| **Dockerfile Path** | `experiments/render/Dockerfile` |
| **Docker Build Context Directory** | leave blank (repository root) |
| Instance Type | **Free** |
| Health Check Path | `/health` |
| Auto-Deploy | Yes (so pushes rebuild) |

Root Directory and the build context **must stay at the repository root** —
the Dockerfile copies `app.py`, `templates/`, `static/` and the rest from
there. Pointing Root Directory at `experiments/render` will fail the build.

### Environment variables

Add these under **Environment** (this deployment has no Settings-written file
to fall back on — anything entered in the app's ⚙ Settings is lost on restart,
so put the keys here):

| Key | Example | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | `gemini` | or `deepseek` |
| `GEMINI_API_KEY` | `AIza…` | whichever provider you chose |
| `DEEPSEEK_API_KEY` | `sk-…` | only if using DeepSeek |
| `GEMINI_MODEL` | `gemini-3.8-flash` | optional; omit for the default |
| `REXTBOOKS_PDF_TIMEOUT` | `300` | optional; raise if exports time out |
| `REXTBOOKS_SECRET_KEY` | (long random) | optional but recommended — otherwise every deploy invents a new one and logs everyone out of their key bundle |
| `REXTBOOKS_KEY_BUNDLES` | `{"rk-mum-…":{"label":"Mum","gemini":"AIza…","pexels":"…"}}` | optional — "master key" bundles, see below |

### Key bundles ("master keys")

A passcode that fills in several provider keys at once, for someone who
shouldn't be pasting a Gemini key, a DeepSeek key and a Pexels key separately.

Set `REXTBOOKS_KEY_BUNDLES` (a **secret** — it contains the real keys) to JSON
whose top-level keys are the passcodes people type:

```json
{
  "rk-mum-8f3a91c2d5e64b70a1c9b3e5d7f9": {
    "label": "Mum",
    "provider": "gemini",
    "keys": { "gemini": "AIza…", "pexels": "…" }
  },
  "rk-me-2b91d7e4c6a84f0e9d13c5a7b9e1": {
    "label": "Me",
    "provider": "deepseek",
    "keys": { "deepseek": "sk-…", "gemini": "AIza…" }
  },
  "rk-lite-9c4e1d7a3b5062fd8e21c4a6b8d0": {
    "label": "Lite plan",
    "keys": { "gemini": "AIza…" },
    "models": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
  }
}
```

Generate a passcode with:

```bash
python -c "import secrets; print('rk-' + secrets.token_hex(16))"
```

How it behaves:

- Entering a passcode via the **🔑 icon beside the Settings title** (a small
  popover — invisible unless bundles are configured) unlocks it **for that
  browser only** (a signed cookie holding an opaque bundle id — never the
  passcode, never a key), so two people on the same instance keep their own
  keys and cannot overwrite each other's. It survives redeploys as long as
  `REXTBOOKS_SECRET_KEY` is set.
- While unlocked, the bundle supplies the provider, the keys (and the model if
  the bundle sets one); those controls are disabled in Settings, because
  writing them would change the shared settings file.
- **Restricting the models a plan may use.** Add `"models": [...]` to a bundle
  and that becomes a hard limit: Settings lists only those models (no "Custom
  model…"), and the server refuses anything else even if the API is called
  directly. `"model": "…"` is the strict version — one model, no choice — and
  `"models": {"gemini": [...], "deepseek": [...]}` sets a different list per
  provider. Without either, the user picks any model, as before. Each browser's
  model choice is kept in its own session, so two people on one bundle don't
  overwrite each other (and nothing is written to `local_settings.json`).
- Unlock attempts are rate-limited (10 per 5 minutes per IP), comparisons are
  constant-time, and nothing about the passcode is logged or written to disk.
- Removing a bundle from the env var revokes it immediately.
- Treat each passcode like a password: whoever has it spends the keys inside
  it. Put a spend limit on the shared Gemini key.

`BOOKS_DIR=/data/books` is already set by the Dockerfile. Do **not** add a
persistent disk — free instances can't have one, and this test doesn't need it.

---

## 3. First deploy

The build installs Chromium and the Python dependencies, so expect a few
minutes for the first deploy. When it finishes, open the `onrender.com` URL.

The service spins down after 15 minutes of inactivity; the next visit shows
Render's loading page for roughly a minute before the app appears. That is
normal on the free tier, not a fault.

---

## 4. What to test (the actual point)

1. **Basic use** — create a book, generate an outline, generate one section.
   This confirms gunicorn + SSE streaming works through Render's proxy (watch
   the text appear progressively rather than all at once).
2. **Math and diagrams** — generate a section containing a formula and a
   Mermaid diagram; both should render in the preview.
3. **PDF export** — Export → PDF. This is the memory test: Chromium needs a
   few hundred MB on top of Flask.
4. **EPUB export** — the second-biggest request (it launches Chromium again for
   diagram rasterisation).
5. **Restart behaviour** — from the Render dashboard, *Manual Deploy → Restart*,
   then reload: the book should be gone. That is the ephemeral filesystem
   confirming why the stateless port matters.

### Reading the result

- **Exports succeed** → 512 MB is enough for a modest book, so the stateless
  version can live on the free tier at $0 (with the cold-start delay).
- **Export kills the service** (the page 502s, the dashboard shows a restart or
  an out-of-memory event, and the logs stop mid-export) → 512 MB is not enough
  for hosted exports. Options then are: $25/mo for 2 GB, keep exports local, or
  move PDF/EPUB generation into the browser.
- **Exports are merely slow** (minutes) → that's the 0.1-CPU free instance, not
  a failure. Timing tells you whether it's usable, not whether it fits.

Use **Logs** in the dashboard during each export; the app prints export and
image-resolution progress to stderr, so a cut-off log is the clearest OOM
signal.

### Tuning a small instance (what actually helps)

Timeouts and concurrency fix *different* failure modes — worth knowing which
one you have before changing anything:

| Symptom | Cause | Does a longer timeout help? |
| --- | --- | --- |
| Export returns 504 "timed out (tried twice)" | 0.1 CPU is simply slow | Yes — raise `REXTBOOKS_PDF_TIMEOUT` |
| Page 502s / service restarts / logs stop mid-export | Out of memory | **No** — it was killed, not slow |

For out-of-memory, concurrency is the lever, and *less* of it is the fix:

- **Exports are serialised inside the app** (`pdfgen._BROWSER_LOCK`): only one
  headless Chromium runs at a time, so a second export queues instead of
  starting a second browser. Everything else — page loads, AI streams — is
  unaffected. Verified locally: two PDF exports requested at once finish in
  4.0 s and 7.6 s (one waited), wall time 7.6 s — with two browsers they would
  have run in parallel at double the peak memory.
- **Chromium runs container-friendly flags** (`pdfgen._MEMORY_FLAGS`), the
  important one being `--disable-dev-shm-usage` — Docker's `/dev/shm` is 64 MB
  by default and Chromium's renderer crashes or gets OOM-killed without it.
- **A timed-out browser is killed as a process group** on Linux, so orphaned
  renderer processes can't keep leaking memory after a failed attempt (a
  retry then starts from a clean slate).
- If it still dies, in this order: turn on **Lite** in the Export dialog (fewer
  pixels, same layout), export **chapters separately** via "Content to
  include", drop `--threads 8` to `--threads 4` in the Dockerfile `CMD` (fewer
  request threads competing for the same 512 MB), and only then move to the
  $7 (0.5 CPU) / $25 (1 CPU, 2 GB) instance.
- `--max-requests 50 --max-requests-jitter 10` can be added to the gunicorn
  `CMD` if memory creeps over a long uptime — it recycles the worker instead
  of letting a slow leak accumulate. With one worker, a recycle is a brief
  queue, not a dropped request.

---

## 5. Cleaning up

**Settings → Suspend Service** stops it (and stops consuming free instance
hours), or delete the service. Free workspaces get 750 instance-hours a month,
which is why it's worth suspending when you're done testing.

---

## Optional: blueprint instead of clicking

If you'd rather reproduce the setup from a file, a `render.yaml` at the
repository root is equivalent to the table above:

```yaml
services:
  - type: web
    name: rextbooks-test
    runtime: docker
    plan: free
    dockerfilePath: ./experiments/render/Dockerfile
    dockerContext: .
    healthCheckPath: /health
    autoDeploy: true
    envVars:
      - key: LLM_PROVIDER
        value: gemini
      - key: GEMINI_API_KEY
        sync: false          # Render prompts for the value, never stores it in git
```

`sync: false` is important: it marks the key as a secret to be entered in the
dashboard rather than committed.

---

## Why the start command looks like that

- `gunicorn app:app` — the app object, not `python app.py`; the built-in
  `app.run(host="127.0.0.1", port=5000)` only works locally.
- `--bind 0.0.0.0:${PORT}` — Render assigns the port and requires binding all
  interfaces.
- `--worker-class gthread --threads 8` — one worker that can stream an SSE
  generation while still answering other requests (the default sync worker
  would serialise them).
- `--timeout 1200` — generation can take ~1–2 minutes (longer with the length
  extension) and an export can take minutes; the default 30 s would kill it.
- `--forwarded-allow-ips="*"` — trusts Render's proxy headers so the app builds
  `https://…` preview URLs for Chromium instead of `http://…`.
- `--access-logfile -` / `--error-logfile -` — send logs to Render's log view.
