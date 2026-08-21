"""Deterministic Spool materializer — the kit's generation, model-free.

Scenario: **deflection decay after a KB re-index.** A support-triage agent answers
customer tickets. Midway through the window the knowledge base is re-indexed (`kb-v1` →
`kb-v2`) and retrieval quietly gets worse: top-chunk relevance drops, the agent runs more
retrieval rounds, stuffs more context into the drafting model, and hands off to a human far
more often. Nothing throws. The only visible symptoms are the ones an observability tool is
supposed to surface — deflection rate down, cost per ticket up, latency up.

Everything here derives from the seeded `Rng` and the `run_date` anchor `synth.seed` hands
in — the operator's as-of date, or now when none was set (portal #229) — so the same inputs
yield a byte-identical Spool every run, on any day. No model call, no network, no wall
clock, and no date constant: every date in the story is an OFFSET from `run_date`. The
determinism golden gate runs this under a deny-LLM egress block and pins the anchor in
`tests/golden_seed.py`, where determinism belongs.

Langfuse data-model choices (made against current docs, not memory):

* **Sessions** group the turns of one ticket (`sessionId`, 1:n to traces) so the demo can
  replay a whole conversation, and carry the headline `deflected` outcome as a
  *session-level* score — the documented use for "evaluation across multiple interactions".
* **Observation types** use the agent-graph vocabulary (`AGENT` / `RETRIEVER` / `TOOL`)
  via the library's `observation_event`. On the OTLP wire (portal #210) these land as
  their real types — the agent graph shows up natively in Langfuse instead of degraded
  spans carrying `metadata.observation_type`.
* **Usage details are mutually exclusive buckets** per the token-tracking contract:
  `input` *excludes* `input_cached_tokens`. Overlapping buckets double-count cost.
* **Score data types** follow the scores data model: NUMERIC carries a number, CATEGORICAL
  carries a string, BOOLEAN carries 0/1.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from langfuse_synth_core.rng import Rng
from langfuse_synth_core.seed.events import (
    generation_event,
    observation_event,
    score_event,
    trace_event,
)
from langfuse_synth_core.timegen import sample_timestamps

from .config import DERIVATION_HOOK

# The backdated window ends at the run anchor and reaches this many days back.
WINDOW_DAYS = 28

# The regression boundary: the KB re-index lands this many days before the run anchor,
# leaving a long healthy baseline before it and a clearly degraded tail after it.
REINDEX_OFFSET_DAYS = 10


def reindex_at(run_date: datetime) -> datetime:
    """When the KB re-index landed, relative to the run anchor.

    `verify` runs in a different container, possibly days later, and is never told the
    anchor — it derives one from the newest data it reads and applies this same offset
    (see `synth.verify`). Keep the two in step through this function.
    """
    return run_date - timedelta(days=REINDEX_OFFSET_DAYS)

INTENTS = ("billing", "technical", "account", "shipping")
CHANNELS = ("web-widget", "email", "in-app")

# Turns per ticket: most tickets are one-and-done; a tail runs long.
TURNS_PER_TICKET = (1, 2, 3)
TURNS_WEIGHTS = (0.55, 0.30, 0.15)

CUSTOMER_POOL = 240

# Two synthetic models so the demo shows a realistic model mix: a cheap classifier and an
# expensive drafter. Prices are USD per token; cost is ingested explicitly (ingested cost
# always wins over inference), so these names need no model definition in Langfuse.
CLASSIFIER_MODEL = "synthetic-mini-v1"
DRAFTER_MODEL = "synthetic-pro-v1"
PRICE = {
    CLASSIFIER_MODEL: {"input": 0.15e-6, "output": 0.60e-6, "input_cached_tokens": 0.015e-6},
    DRAFTER_MODEL: {"input": 2.50e-6, "output": 10.00e-6, "input_cached_tokens": 0.25e-6},
}

# The drafter's system prompt is prompt-cached, so those tokens bill at the cached rate and
# MUST NOT also be counted in `input` (the mutually-exclusive-buckets contract).
CACHED_SYSTEM_TOKENS = 1200
TOKENS_PER_CHUNK = 220

# Relevance below this and the agent cannot stand behind an answer — it escalates.
RELEVANCE_ESCALATION_FLOOR = 0.55


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _cost(model: str, usage: Mapping[str, int]) -> dict:
    """USD per usage bucket, plus the explicit total. Mirrors `usage` bucket-for-bucket."""
    prices = PRICE[model]
    out = {k: round(v * prices[k], 10) for k, v in usage.items() if k in prices}
    out["total"] = round(sum(out.values()), 10)
    return out


def _retrieval_profile(r: Rng, post_reindex: bool) -> tuple[int, float]:
    """(rounds, best_relevance) — the single knob the whole regression turns on.

    Before the re-index the first query usually nails it. After it, top-chunk relevance
    collapses, so the agent retries — more rounds, more context, more cost.
    """
    if post_reindex:
        rounds = r.choices(TURNS_PER_TICKET, (0.30, 0.42, 0.28), k=1)[0]
        best = _clamp01(r.gauss(0.58, 0.13))
    else:
        rounds = r.choices(TURNS_PER_TICKET, (0.78, 0.18, 0.04), k=1)[0]
        best = _clamp01(r.gauss(0.84, 0.07))
    return rounds, best


def build_events(
    target_traces: int, params: Mapping[str, Any], *, run_date: datetime
) -> list[dict]:
    """Materialize the full pre-ingestion event stream, deterministically.

    `target_traces` is a direct trace (turn) count — the identity derivation — and tickets
    are formed by grouping consecutive turns, so the operator's one knob stays exact.
    `run_date` is the resolved as-of anchor: the window ends there and the re-index sits
    `REINDEX_OFFSET_DAYS` before it.
    """
    internal = DERIVATION_HOOK(target_traces, params)
    count = int(internal["target_traces"])
    seed = int(params.get("seed", 42))
    rng = Rng(seed)
    boundary = reindex_at(run_date)
    timestamps = sample_timestamps(rng.sub("timestamps"), run_date, WINDOW_DAYS, count)

    events: list[dict] = []

    ticket_index = -1
    turns_left = 0
    turn_no = 0
    ticket: dict[str, Any] = {}

    def close_ticket() -> None:
        """Emit the session-level outcome score for the ticket that just ended."""
        if not ticket:
            return
        deflected = 0 if ticket["escalated"] else 1
        events.append(
            score_event(
                score_id=ticket["rng"].score_id("deflected"),
                name="deflected",
                value=deflected,
                data_type="BOOLEAN",
                timestamp=ticket["last_ts"],
                session_id=ticket["session_id"],
                comment=(
                    "handed off to a human agent"
                    if ticket["escalated"]
                    else "resolved without human involvement"
                ),
            )
        )

    for i, ts in enumerate(timestamps):
        # --- ticket / session bookkeeping -------------------------------------------------
        if turns_left == 0:
            close_ticket()
            ticket_index += 1
            tr = rng.sub("ticket", ticket_index)
            turns_left = tr.choices(TURNS_PER_TICKET, TURNS_WEIGHTS, k=1)[0]
            turn_no = 0
            ticket = {
                "rng": tr,
                "session_id": f"SUP-{ticket_index:06d}",
                "user_id": f"cust-{tr.randint(0, CUSTOMER_POOL - 1):04d}",
                "intent": tr.choice(INTENTS),
                "channel": tr.choice(CHANNELS),
                "escalated": False,
                "last_ts": ts,
            }
        turns_left -= 1
        turn_no += 1
        ticket["last_ts"] = ts

        r = rng.sub("turn", i)
        post = ts >= boundary
        index_version = "kb-v2" if post else "kb-v1"
        trace_id = r.trace_id(i)

        rounds, best_relevance = _retrieval_profile(r, post)
        escalate = best_relevance < RELEVANCE_ESCALATION_FLOOR or r.chance(0.06)

        # --- timeline ---------------------------------------------------------------------
        # Built forward from the trace start so the agent span always encloses its children.
        cursor = ts
        agent_start = cursor
        cursor += timedelta(milliseconds=40)

        classify_start = cursor
        classify_end = classify_start + timedelta(milliseconds=r.randint(180, 420))
        cursor = classify_end

        # --- trace root -------------------------------------------------------------------
        events.append(
            trace_event(
                trace_id=trace_id,
                timestamp=ts,
                name="support-triage-turn",
                user_id=ticket["user_id"],
                session_id=ticket["session_id"],
                tags=["support", "triage", ticket["intent"], index_version],
                metadata={
                    "intent": ticket["intent"],
                    "channel": ticket["channel"],
                    "turn": turn_no,
                    "kb_index_version": index_version,
                    "post_reindex": post,
                },
                input={"ticket": ticket["session_id"], "intent": ticket["intent"]},
            )
        )

        agent_id = r.obs_id(i, "agent")

        # --- classify the intent (cheap model) --------------------------------------------
        cls_in, cls_out = r.randint(120, 260), r.randint(8, 24)
        cls_usage = {"input": cls_in, "output": cls_out, "total": cls_in + cls_out}
        events.append(
            generation_event(
                obs_id=r.obs_id(i, "classify"),
                trace_id=trace_id,
                parent_id=agent_id,
                name="classify-intent",
                start=classify_start,
                end=classify_end,
                model=CLASSIFIER_MODEL,
                usage_details=cls_usage,
                cost_details=_cost(CLASSIFIER_MODEL, cls_usage),
                input={"subject": f"{ticket['intent']} question"},
                output={"intent": ticket["intent"]},
            )
        )

        # --- retrieval rounds (the regression lives here) ----------------------------------
        chunks_total = 0
        for k in range(rounds):
            rr = r.sub("retrieval", k)
            # Round 0 is the reported `best_relevance`; retries claw back a little less.
            relevance = (
                best_relevance if k == 0 else _clamp01(best_relevance - rr.uniform(0.02, 0.12))
            )
            chunks = rr.randint(3, 6)
            chunks_total += chunks
            ret_start = cursor
            ret_end = ret_start + timedelta(
                milliseconds=rr.randint(220, 520) + (140 if post else 0)
            )
            cursor = ret_end
            ret_id = r.obs_id(i, "retrieve", k)
            events.append(
                observation_event(
                    obs_id=ret_id,
                    trace_id=trace_id,
                    parent_id=agent_id,
                    name="kb-search",
                    obs_type="RETRIEVER",
                    start=ret_start,
                    end=ret_end,
                    input={"query": f"{ticket['intent']} help", "top_k": chunks},
                    output={"chunks": chunks, "top_score": round(relevance, 6)},
                    metadata={
                        "kb_index_version": index_version,
                        "round": k + 1,
                        "top_score": round(relevance, 6),
                    },
                )
            )
            # Observation-level score: relevance belongs to the retrieval step, not the turn.
            events.append(
                score_event(
                    score_id=r.score_id(i, "relevance", k),
                    name="retrieval_relevance",
                    value=round(relevance, 6),
                    data_type="NUMERIC",
                    timestamp=ret_end,
                    trace_id=trace_id,
                    observation_id=ret_id,
                )
            )

        # --- draft the reply (expensive model; context scales with retrieved chunks) -------
        draft_start = cursor
        draft_in = r.randint(320, 560) + chunks_total * TOKENS_PER_CHUNK
        draft_out = r.randint(90, 260)
        draft_usage = {
            # `input` deliberately EXCLUDES the cached system prompt — buckets must not overlap.
            "input": draft_in,
            "input_cached_tokens": CACHED_SYSTEM_TOKENS,
            "output": draft_out,
            "total": draft_in + CACHED_SYSTEM_TOKENS + draft_out,
        }
        draft_end = draft_start + timedelta(milliseconds=600 + draft_out * 8)
        cursor = draft_end
        events.append(
            generation_event(
                obs_id=r.obs_id(i, "draft"),
                trace_id=trace_id,
                parent_id=agent_id,
                name="draft-reply",
                start=draft_start,
                end=draft_end,
                completion_start=draft_start + timedelta(milliseconds=r.randint(180, 400)),
                model=DRAFTER_MODEL,
                usage_details=draft_usage,
                cost_details=_cost(DRAFTER_MODEL, draft_usage),
                input={"context_chunks": chunks_total, "intent": ticket["intent"]},
                output={"escalate": escalate},
                metadata={"context_chunks": chunks_total, "kb_index_version": index_version},
            )
        )

        # --- hand off to a human, when the agent cannot stand behind the answer ------------
        if escalate:
            ticket["escalated"] = True
            esc_start = cursor
            esc_end = esc_start + timedelta(milliseconds=r.randint(90, 210))
            cursor = esc_end
            events.append(
                observation_event(
                    obs_id=r.obs_id(i, "escalate"),
                    trace_id=trace_id,
                    parent_id=agent_id,
                    name="escalate-to-human",
                    obs_type="TOOL",
                    start=esc_start,
                    end=esc_end,
                    input={"queue": ticket["intent"], "reason": "low_confidence"},
                    output={"ticket": ticket["session_id"], "queued": True},
                    level="WARNING",
                    status_message="handed off: retrieved context below confidence floor",
                )
            )

        # --- the agent span encloses the whole turn ----------------------------------------
        events.append(
            observation_event(
                obs_id=agent_id,
                trace_id=trace_id,
                name="triage-agent",
                obs_type="AGENT",
                start=agent_start,
                end=cursor,
                input={"intent": ticket["intent"], "turn": turn_no},
                output={"escalated": escalate, "retrieval_rounds": rounds},
                metadata={"kb_index_version": index_version, "retrieval_rounds": rounds},
            )
        )

        # --- trace-level scores -------------------------------------------------------------
        # Groundedness tracks the evidence the drafter actually had to work with.
        events.append(
            score_event(
                score_id=r.score_id(i, "groundedness"),
                name="groundedness",
                value=round(_clamp01(best_relevance - r.uniform(0.0, 0.10)), 6),
                data_type="NUMERIC",
                timestamp=draft_end,
                trace_id=trace_id,
                comment="fraction of the reply supported by retrieved context",
            )
        )
        events.append(
            score_event(
                score_id=r.score_id(i, "resolution"),
                name="resolution",
                value="escalated" if escalate else "self_served",
                data_type="CATEGORICAL",
                timestamp=cursor,
                trace_id=trace_id,
            )
        )

        # Explicit user feedback is sparse, and skews negative when the turn went badly —
        # the documented reality of thumbs-up/down capture.
        if r.chance(0.34 if escalate else 0.18):
            happy = r.chance(0.25 if escalate else 0.88)
            events.append(
                score_event(
                    score_id=r.score_id(i, "user_feedback"),
                    name="user_feedback",
                    value=1 if happy else 0,
                    data_type="BOOLEAN",
                    timestamp=cursor + timedelta(seconds=r.randint(20, 900)),
                    trace_id=trace_id,
                    comment="thumbs up" if happy else "thumbs down",
                )
            )

    close_ticket()
    return events
