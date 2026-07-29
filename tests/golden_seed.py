"""Golden-gate seed adapter (dev-only; never shipped in the runtime image).

The determinism golden gate in `langfuse-synth-core[authoring]` drives a kit through one
contract — `seed(target_traces, params) -> bytes` (the full materialized Spool). This
adapter drives the REAL runtime seed path (`synth.seed.run_seed` in dry-run: spool through
the library's `Ingestor`, no network, no ingestion) and returns the resulting Spool bytes,
so the gate proves the actual `synth seed` is deterministic AND model-free — not a parallel
materializer that could drift from it.

It lives in `tests/` because the gate is authoring-time tooling behind the `[authoring]`
extra; the deployed runtime image must never carry it (Spec A §3). The gate imports it via
`search_paths`, in a subprocess under PYTHONHASHSEED=0 and the deny-LLM egress block.
"""
from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from synth.config import load_config
from synth.seed import run_seed

CONFIG = Path(__file__).resolve().parent.parent / "config" / "demo.yaml"


def seed(target_traces: int, params: Mapping[str, Any]) -> bytes:
    """Materialize the full pre-ingestion Spool for `target_traces` through the runtime seed
    path; return its bytes.

    `target_traces` is set exactly as the portal sets it (`--set generation.target_traces=N`),
    so this proves the operator knob end to end. `params` completes the gate contract; the
    skeleton derives volume from the knob alone (identity hook), so it reads config defaults
    for the rest.
    """
    cfg = load_config(str(CONFIG), overrides=[f"generation.target_traces={int(target_traces)}"])
    with tempfile.TemporaryDirectory(prefix="synth-golden-") as tmp:
        spool_path = Path(tmp) / "events.ndjson"
        # dry_run: no guardrail call, no network; do_import=False: never touch Langfuse.
        run_seed(cfg, dry_run=True, do_import=False, spool_path=spool_path, log=lambda _m: None)
        return spool_path.read_bytes()
