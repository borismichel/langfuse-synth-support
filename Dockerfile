# Reference Dockerfile for a Demo Depot synth kit (non-root uid/gid 10001).
# Mirrors langfuse-synth-core/examples/kit.Dockerfile. langfuse-synth-core is a PUBLIC git
# dependency pinned in pyproject.toml, so the install is a plain HTTPS pip install — no
# build secret.
#
# Build:  docker build -t support-triage-deflection:dev .

FROM python:3.12-slim

# git: python:*-slim ships without it, but pip needs it to fetch the git-pinned lib.
# The repo is public, so this is a plain HTTPS fetch — no build secret required.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (uid/gid 10001) — job & live containers never run as root.
RUN groupadd --gid 10001 synth \
 && useradd --uid 10001 --gid synth --create-home --home-dir /home/synth synth

WORKDIR /app
COPY . .

# Fetches the pinned public lib over HTTPS during the build; nothing to authenticate.
RUN pip install --no-cache-dir .

# Runtime write paths, owned by the job uid before the drop: /app/out (artifact
# collection — contract) and /app/.synth_spool (the reference seed's spool). COPY
# lands root-owned and job containers run as JOB_RUN_USER=10001:10001, so without
# this line seed dies on open_spool() at its first deployment (portal #189).
RUN mkdir -p /app/out /app/.synth_spool && chown -R synth:synth /app

USER synth
# The portal supplies `synth <verb> --config {config}` at container-create time.
