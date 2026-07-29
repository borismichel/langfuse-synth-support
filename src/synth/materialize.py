"""Deterministic Spool materializer — the kit's generation, model-free.

Builds Langfuse ingestion events through the shared library's event builders
(`langfuse_synth_core.seed.events`) and deterministic RNG (`langfuse_synth_core.rng.Rng`).
No model calls, no network — so the seed passes the determinism golden gate under the
deny-LLM egress block. The single operator volume knob `generation.target_traces` flows
through the kit's `DERIVATION_HOOK` (identity by default) at seed time.

This is the one place generation lives: the runtime `synth seed` spools these events
through the library's `Ingestor`, and the golden-gate adapter (`tests/golden_seed.py`)
drives that same seed path in dry-run to read the resulting Spool bytes. Grow the window
and the story here; keep it deterministic.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from langfuse_synth_core.rng import Rng
from langfuse_synth_core.seed.events import generation_event, score_event, trace_event
from langfuse_synth_core.timegen import sample_timestamps

from .config import DERIVATION_HOOK

# Fixed anchor so backdated timestamps are reproducible run-to-run (the gate materializes
# in a subprocess and may read no wall clock). Grow the window/story as the kit does.
RUN_DATE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
WINDOW_DAYS = 14
_TASKS = ("chat", "search", "summarize", "classify")


def build_events(target_traces: int, params: Mapping[str, Any]) -> list[dict]:
    """Materialize the full pre-ingestion event stream, deterministically.

    The canonical volume knob flows through `DERIVATION_HOOK` to the kit's internal count;
    every id, timestamp, and value derives from the seeded `Rng`, so the same inputs yield
    a byte-identical Spool every run (params-inclusive).
    """
    internal = DERIVATION_HOOK(target_traces, params)
    count = int(internal["target_traces"])
    seed = int(params.get("seed", 42))
    rng = Rng(seed)
    timestamps = sample_timestamps(rng.sub("timestamps"), RUN_DATE, WINDOW_DAYS, count)

    events: list[dict] = []
    for i, ts in enumerate(timestamps):
        r = rng.sub("trace", i)
        trace_id = r.trace_id(i)
        task = r.choice(_TASKS)
        events.append(
            trace_event(trace_id=trace_id, timestamp=ts, name=task, metadata={"task": task})
        )

        in_tokens = r.randint(50, 500)
        out_tokens = r.randint(10, 200)
        events.append(
            generation_event(
                obs_id=r.obs_id(i),
                trace_id=trace_id,
                name="llm-call",
                start=ts,
                end=ts,
                model="synthetic-model-v1",
                usage_details={
                    "input": in_tokens,
                    "output": out_tokens,
                    "total": in_tokens + out_tokens,
                },
                cost_details={"input": 0.0, "output": 0.0, "total": 0.0},
                input={"task": task},
                output={"ok": True},
            )
        )

        events.append(
            score_event(
                score_id=r.score_id(i),
                name="quality",
                value=round(r.uniform(0.0, 1.0), 6),
                data_type="NUMERIC",
                timestamp=ts,
                trace_id=trace_id,
            )
        )
    return events
