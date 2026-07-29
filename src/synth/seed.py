"""`synth seed` runtime path — materialize the Spool, then ingest it through the library.

Two-phase, library-owned: spool every event to disk first, then batch-import in chunks
(`langfuse_synth_core.seed.ingest.Ingestor`). Network never runs interleaved with
generation, so a wedged upload can't lose the deterministic data — re-run to resume
(idempotent upsert on the deterministic ids). Generation is model-free (see
`synth.materialize`), so a re-seed is safe and the determinism gate can prove it offline.
"""
from __future__ import annotations

from pathlib import Path

from langfuse_synth_core.seed.ingest import Ingestor, assert_demo_project

from .config import Config
from .materialize import build_events

DEFAULT_SPOOL = Path(".synth_spool") / "events.ndjson"


def run_seed(
    cfg: Config,
    *,
    dry_run: bool = False,
    do_import: bool = True,
    spool_path: str | Path | None = None,
    log=print,
) -> Path:
    """Generate the Spool and (unless `dry_run`) ingest it into the target Langfuse project."""
    spool_path = Path(spool_path) if spool_path else DEFAULT_SPOOL
    events = build_events(cfg.generation.target_traces, {"seed": cfg.generation.seed})

    # Guardrail: refuse to run unless the key's project name matches `project_hint`.
    if not dry_run:
        _project_id, project_name = assert_demo_project(cfg.target.base_url, cfg.target.project_hint)
        log(f"✓ guardrail passed: project {project_name!r} matches hint {cfg.target.project_hint!r}")

    ingestor = Ingestor.from_env(cfg.target.base_url, dry_run=dry_run, spool_path=spool_path)
    ingestor.open_spool()
    ingestor.extend(events)
    ingestor.close_spool()
    log(f"· spooled {ingestor.spooled} events -> {spool_path}")

    if do_import and not dry_run:
        sent = ingestor.import_spool(path=spool_path, log=log)
        log(f"✓ imported {sent} events")
    return spool_path
