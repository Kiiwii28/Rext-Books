# Deployment-only image for the "does the app fit on Render's free tier?" test.
#
# It runs the application exactly as it is — no source changes, no duplicated
# copy. The Render service is configured with:
#     Root Directory      = (blank — repo root)
#     Runtime             = Docker
#     Dockerfile Path     = experiments/render/Dockerfile
#     Build Context       = (blank — repo root)
# so the build context is the whole repository and the COPY lines below pick
# out only the files the app needs at runtime. `.dockerignore` at the repo root
# keeps the virtualenv, the portable build, real books and API keys out of it.
#
# What this image is NOT: the stateless/BYOK variant. Books and settings are
# written inside the container and lost on every restart, which is fine for a
# one-off benchmark of memory use and export behaviour.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BOOKS_DIR=/data/books

# Chromium is what pdfgen.py shells out to for PDF and EPUB export; the font
# packages keep printed books from falling back to tofu boxes. Debian's
# `chromium` installs /usr/bin/chromium, which pdfgen.find_browser() finds by
# name, so no REXTBOOKS_CHROME override is needed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        chromium fonts-liberation fonts-dejavu-core ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# gunicorn is deployment-only, so it is installed here rather than being added
# to the project's requirements.txt.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Runtime files only. books/, local_settings.json and .env must never be baked
# into an image (the root .dockerignore enforces this as well).
#
# `*.py` rather than an itemised list on purpose: this list used to name every
# module explicitly, and adding a new one (`bundle.py`, for the JSON+images
# export) meant the image booted with `ModuleNotFoundError: No module named
# 'bundle'` while the same code ran fine locally. Every .py at the repo root is
# an app module — the portable build and any scratch scripts live in folders
# that .dockerignore already drops — so globbing can't miss one.
COPY *.py prompts.defaults.json ./
COPY templates ./templates
COPY static ./static

RUN mkdir -p /data/books

EXPOSE 10000

# gthread (rather than the default sync worker) is what lets one worker stream
# an SSE generation while other requests are still answered. --timeout is
# generous because a PDF/EPUB export can take minutes on a 0.1-CPU instance.
# --forwarded-allow-ips is required behind Render's proxy so Flask sees the
# real scheme/host (https://…) when it builds the preview URL that Chromium
# prints.
CMD exec gunicorn app:app \
        --bind 0.0.0.0:${PORT:-10000} \
        --workers 1 \
        --worker-class gthread \
        --threads 8 \
        --timeout 1200 \
        --graceful-timeout 30 \
        --forwarded-allow-ips="*" \
        --access-logfile - \
        --error-logfile -
