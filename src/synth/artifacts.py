"""Artifact output paths for portal-collected kit files.

Per `CONTRACT.md` ("Filesystem conventions") the worker collects declared artifacts from
the container's `/app/out/` after the producing step exits. The committed `DEMO_SCRIPT.md`
at the repo root is the *source*; `synth seed` publishes a copy into the artifact dir so
the portal has something to collect. Outside a container — a local `synth seed` run — the
`/app/out` mkdir fails and we fall back to the repo root, which keeps local runs working
without pretending they are deployments.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timezone

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


def publish_schedule(spool_path: Path, run_date: datetime, history_days: int, log=print) -> Path:
    """Publish the requested calendar and the finalized Spool's observation bounds."""
    earliest = latest = None
    with spool_path.open() as spool:
        for line in spool:
            event = json.loads(line)
            if "spanId" not in event:
                continue
            start, end = int(event["startTimeUnixNano"]), int(event["endTimeUnixNano"])
            earliest = start if earliest is None else min(earliest, start)
            latest = end if latest is None else max(latest, end)
    def iso(nanos: int) -> str:
        return datetime.fromtimestamp(nanos / 1e9, timezone.utc).isoformat().replace("+00:00", "Z")
    path = artifact_path("SCHEDULE.json")
    path.write_text(json.dumps({
        "version": 1,
        "requested": {"as_of_date": run_date.date().isoformat(), "history_days": history_days,
                      "timezone": "UTC", "end": "inclusive"},
        "generated_range": {"start": iso(earliest), "end": iso(latest), "timezone": "UTC"}
                           if earliest is not None else None,
    }, indent=2) + "\n")
    log(f"· published generated schedule -> {path}")
    return path
