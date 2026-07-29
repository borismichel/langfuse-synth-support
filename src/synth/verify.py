"""`synth verify` — read the data back through the library and assert it landed.

The read-client (auth + paginated GETs of the Langfuse public REST API) is the library's
(`langfuse_synth_core.lfread`); what stays HERE is the scenario talking — which assertions
to make about what landed. The walking skeleton asserts the floor: traces are visible and
the `quality` score family is present. Grow the checks as the story grows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from langfuse_synth_core.lfread import get_all_scores, get_json

from .config import Config


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
    """Query the target project back and report each floor check pass/fail."""
    base = cfg.target.base_url
    report = VerifyReport()

    traces = get_json(base, "/api/public/traces", {"limit": 1})
    total = traces.get("meta", {}).get("totalItems")
    if total is None:
        total = len(traces.get("data", []))
    report.add("traces_present", total > 0, f"{total} trace(s) visible")

    scores = get_all_scores(base, "quality")
    report.add("quality_scores_present", len(scores) > 0, f"{len(scores)} quality score(s)")

    for check in report.checks:
        log(f"{'✓' if check.ok else '✗'} {check.name}: {check.detail}")
    return report
