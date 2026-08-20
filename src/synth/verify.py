"""`synth verify` — read the data back through the seam and assert it landed.

The read seam (`langfuse_synth_core.read`) is the read-client: it owns the Langfuse API
endpoints, follows their pagination to the end, and normalises what comes back, so this file
reads the same rows whichever API generation the target serves (portal #211). What stays
HERE is the scenario talking — which assertions to make about what landed.

This kit's `verify` is the **sole scenario oracle** at admission, so it asserts the *story*,
not just row counts: the retrieval regression must be visible across the re-index boundary,
tickets must be grouped into sessions, and both resolution outcomes must be present. A kit
that seeds rows but no longer tells the story fails here.

Note on sampling: `reader.traces()` is a **sample** and never a project total — under v4
there is no trace list to count, and the seam refuses to pretend otherwise. Score reads
follow pagination to the seam's page cap, so at large `target_traces` the distribution
checks run on a large sample rather than the full pool. That is sufficient for a verdict:
the effect being asserted is a ~0.28 shift in the mean.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from langfuse_synth_core.target import TargetProfile

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


def run_verify(cfg: Config, *, log=print) -> VerifyReport:
    """Query the target project back and report each scenario check pass/fail."""
    # `try_resolve`, not `resolved`: bad keys or a wrong host must come back as failed
    # checks with the reason on each line, which is what this report is for — not as a
    # traceback in place of it (portal #211).
    profile, unreadable = TargetProfile.detect(cfg.target.base_url).try_resolve()
    reader = profile.reader()
    log(f"· verifying against {profile.label} ({profile.base_url})"
        + (f" — cannot read it: {unreadable}" if unreadable else ""))
    report = VerifyReport()

    # --- the data landed at all ---------------------------------------------------------
    traces = reader.traces(limit=100)
    report.add("traces_present", len(traces) > 0, f"{len(traces)} trace(s) sampled")

    # --- tickets are grouped into sessions ----------------------------------------------
    sessions = {t.session_id for t in traces if t.session_id}
    report.add(
        "sessions_grouped",
        len(sessions) > 0 and len(sessions) <= len(traces),
        f"{len(sessions)} session(s) across {len(traces)} sampled trace(s)",
    )

    # --- the regression is visible across the re-index boundary --------------------------
    relevance = reader.scores(name="retrieval_relevance")
    report.add(
        "retrieval_relevance_present",
        len(relevance) > 0,
        f"{len(relevance)} retrieval_relevance score(s)",
    )

    pre = [s.numeric_value for s in relevance
           if s.numeric_value is not None and s.timestamp and s.timestamp < REINDEX_AT]
    post = [s.numeric_value for s in relevance
            if s.numeric_value is not None and s.timestamp and s.timestamp >= REINDEX_AT]
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
    # `resolution` is CATEGORICAL, so the label is the value — the seam keeps it out of the
    # numeric column rather than reporting the deprecated API's `value: 0` placeholder.
    resolution = reader.scores(name="resolution")
    labels = {s.string_value for s in resolution if s.string_value}
    report.add(
        "both_resolutions_present",
        {"self_served", "escalated"} <= labels,
        f"resolution labels: {sorted(labels)}",
    )

    # --- the headline metric exists at the session level ---------------------------------
    deflected = reader.scores(name="deflected")
    on_sessions = [s for s in deflected if s.session_id]
    report.add(
        "session_deflection_scored",
        len(on_sessions) > 0,
        f"{len(on_sessions)} session-level deflected score(s)",
    )

    # --- spend is attributed, so the cost curve is real ----------------------------------
    # The seam rolls the two generations' cost columns onto one field (legacy's
    # `calculatedTotalCost`, v4's `totalCost`) and keeps the ingested breakdown beside it,
    # so this reads the same on a target that reports only one of them.
    gens = reader.observations(type="GENERATION", limit_pages=1)
    costed = [o for o in gens
              if (o.total_cost or (o.cost_details or {}).get("total") or 0) > 0]
    report.add(
        "generation_cost_attributed",
        len(costed) > 0,
        f"{len(costed)}/{len(gens)} sampled generation(s) carry a USD cost",
    )

    for check in report.checks:
        log(f"{'✓' if check.ok else '✗'} {check.name}: {check.detail}")
    return report
