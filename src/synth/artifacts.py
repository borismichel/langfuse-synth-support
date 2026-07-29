"""Artifact output paths for portal-collected kit files.

Per `CONTRACT.md` ("Filesystem conventions") the worker collects declared artifacts from
the container's `/app/out/` after the producing step exits. The committed `DEMO_SCRIPT.md`
at the repo root is the *source*; `synth seed` publishes a copy into the artifact dir so
the portal has something to collect. Outside a container — a local `synth seed` run — the
`/app/out` mkdir fails and we fall back to the repo root, which keeps local runs working
without pretending they are deployments.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

DEFAULT_OUT_DIR = Path("/app/out")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RUNBOOK = "DEMO_SCRIPT.md"


def out_dir() -> Path:
    configured = Path(os.environ.get("SYNTH_OUT_DIR") or DEFAULT_OUT_DIR)
    try:
        configured.mkdir(parents=True, exist_ok=True)
        return configured
    except OSError:
        return REPO_ROOT


def artifact_path(name: str) -> Path:
    return out_dir() / name


def publish_runbook(log=print) -> Path | None:
    """Copy the committed Presenter Runbook into the artifact dir; return where it landed.

    A missing source or an unwritable destination is reported and shrugged off: failing the
    seed step over a docs copy would cost the operator the whole dataset.
    """
    source = REPO_ROOT / RUNBOOK
    destination = artifact_path(RUNBOOK)
    if not source.exists():
        log(f"! {RUNBOOK} not found at {source} — nothing to publish")
        return None
    if source.resolve() == destination.resolve():
        return destination  # local run with no artifact dir: the source IS the artifact
    try:
        shutil.copyfile(source, destination)
    except OSError as exc:
        log(f"! could not publish {RUNBOOK} to {destination}: {exc}")
        return None
    log(f"· published {RUNBOOK} -> {destination}")
    return destination
