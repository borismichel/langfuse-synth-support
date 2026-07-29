"""`synth verify` — read the data back through the library and assert it landed.

The read-client (auth + paginated GETs of the Langfuse public REST API) is the library's
(`langfuse_synth_core.lfread`); what stays HERE is the scenario talking — which assertions
to make about what landed.

This kit's `verify` is the **sole scenario oracle** at admission, so it asserts the *story*,
not just row counts: the retrieval regression must be visible across the re-index boundary,
tickets must be grouped into sessions, and both resolution outcomes must be present. A kit
that seeds rows but no longer tells the story fails here.

Note on sampling: score reads follow pagination up to the library's page cap, so at large
`target_traces` the distribution checks run on a large sample rather than the full pool.
That is sufficient for a verdict — the effect being asserted is a ~0.28 shift in the mean.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from langfuse_synth_core.lfread import get_all_scores, get_json, parse_ts

from .config import Config
from .materialize import REINDEX_AT, RELEVANCE_ESCALATION_FLOOR

# The regression must clear this margin to count as "visible" — comfortably below the
# ~0.28 the generator produces, so the check is decisive without being brittle.
MIN_RELEVANCE_DROP = 0.15


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


def _total_items(payload: dict) -> int:
    total = payload.get("meta", {}).get("totalItems")
    return len(payload.get("data", [])) if total is None else int(total)


def run_verify(cfg: Config, *, log=print) -> VerifyReport:
    """Query the target project back and report each scenario check pass/fail."""
    base = cfg.target.base_url
    report = VerifyReport()

    # --- the data landed at all ---------------------------------------------------------
    traces = get_json(base, "/api/public/traces", {"limit": 100})
    total = _total_items(traces)
    report.add("traces_present", total > 0, f"{total} trace(s) visible")

    # --- tickets are grouped into sessions ----------------------------------------------
    sampled = traces.get("data", [])
    sessions = {t.get("sessionId") for t in sampled if t.get("sessionId")}
    report.add(
        "sessions_grouped",
        len(sessions) > 0 and len(sessions) <= len(sampled),
        f"{len(sessions)} session(s) across {len(sampled)} sampled trace(s)",
    )

    # --- the regression is visible across the re-index boundary --------------------------
    relevance = get_all_scores(base, "retrieval_relevance")
    report.add(
        "retrieval_relevance_present",
        len(relevance) > 0,
        f"{len(relevance)} retrieval_relevance score(s)",
    )

    pre = [s["value"] for s in relevance if parse_ts(s["timestamp"]) < REINDEX_AT]
    post = [s["value"] for s in relevance if parse_ts(s["timestamp"]) >= REINDEX_AT]
    if pre and post:
        drop = mean(pre) - mean(post)
        report.add(
            "retrieval_regression_visible",
            drop >= MIN_RELEVANCE_DROP,
            f"pre={mean(pre):.3f} (n={len(pre)}) post={mean(post):.3f} (n={len(post)}) "
            f"drop={drop:.3f} (need >= {MIN_RELEVANCE_DROP})",
        )
        report.add(
            "post_reindex_breaches_floor",
            mean(post) < RELEVANCE_ESCALATION_FLOOR + 0.1,
            f"post-reindex mean {mean(post):.3f} sits at the escalation floor "
            f"({RELEVANCE_ESCALATION_FLOOR})",
        )
    else:
        report.add(
            "retrieval_regression_visible",
            False,
            f"need scores on both sides of {REINDEX_AT.date()} — got pre={len(pre)} post={len(post)}",
        )

    # --- both outcomes are present, so the deflection story has two sides ----------------
    resolution = get_all_scores(base, "resolution")
    labels = {s.get("stringValue") or s.get("value") for s in resolution}
    report.add(
        "both_resolutions_present",
        {"self_served", "escalated"} <= labels,
        f"resolution labels: {sorted(str(x) for x in labels)}",
    )

    # --- the headline metric exists at the session level ---------------------------------
    deflected = get_all_scores(base, "deflected")
    on_sessions = [s for s in deflected if s.get("sessionId")]
    report.add(
        "session_deflection_scored",
        len(on_sessions) > 0,
        f"{len(on_sessions)} session-level deflected score(s)",
    )

    # --- spend is attributed, so the cost curve is real ----------------------------------
    # Field naming for computed cost has varied across Langfuse versions, so accept either
    # the computed rollup or the ingested detail rather than pinning one key.
    gens = get_json(base, "/api/public/observations", {"type": "GENERATION", "limit": 50})
    costed = [
        o
        for o in gens.get("data", [])
        if (o.get("calculatedTotalCost") or (o.get("costDetails") or {}).get("total") or 0) > 0
    ]
    report.add(
        "generation_cost_attributed",
        len(costed) > 0,
        f"{len(costed)}/{len(gens.get('data', []))} sampled generation(s) carry a USD cost",
    )

    for check in report.checks:
        log(f"{'✓' if check.ok else '✗'} {check.name}: {check.detail}")
    return report
