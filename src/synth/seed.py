"""`synth seed` runtime path — materialize the Spool, then ingest it through the library.

Two-phase, library-owned: spool every wire object to disk first, then upload it in chunks
(`langfuse_synth_core.seed.ingest.Ingestor`). Network never runs interleaved with
generation, so a wedged upload can't lose the deterministic data. Generation is model-free
(see `synth.materialize`), so the determinism gate can prove the Spool offline.

**The Spool is written on Langfuse platform v4's transport** (core `docs/WRITE_PATHS.md`;
Cloud goes v4-only on 2026-11-16; this kit's cutover was portal #210 and core deleted the
path it cut over from in #213). Two consequences:

* The Spool is a stream of OTLP spans, and a trace is its root observation. Scores are the
  one thing that stays a `score-create` ingestion envelope, which is the supported v4 path
  for them. Nothing in `synth.materialize` cares either way — the library's event builders
  keep their names and arguments and core owns the wire format.
* **OTLP appends; it does not upsert.** Re-running an import over a partly uploaded Spool
  duplicates observations, so `import-spool` is non-resumable: it fails loudly instead, and
  recovery is to clear the deployment's Langfuse data and import from the top. Determinism
  of the *file* is untouched — that is what the golden gate proves.
"""
from __future__ import annotations

from pathlib import Path

from langfuse_synth_core.seed.ingest import Ingestor, assert_demo_project
from langfuse_synth_core.timegen import resolve_run_date

from .artifacts import publish_runbook
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
    # The run anchor: the operator's as-of date (portal `--set generation.as_of_date=…`),
    # or the wall clock when none was set. The only place either is read — `materialize`
    # takes it as a parameter, which is what makes `seed + target_traces + as-of` the whole
    # input to the Spool's bytes (portal #229).
    run_date = resolve_run_date(cfg.generation.as_of_date)
    log(f"· run anchor {run_date.isoformat()}"
        + (" (as-of date)" if cfg.generation.as_of_date else " (now)"))
    events = build_events(
        cfg.generation.target_traces, {"seed": cfg.generation.seed}, run_date=run_date
    )

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

    # The portal collects declared artifacts from the container's /app/out after this step
    # exits. Skipped under dry_run so the determinism gate stays a pure read of the Spool.
    if not dry_run:
        publish_runbook(log=log)
    return spool_path
