"""`verify` — this kit's sole scenario oracle — reads through the seam (portal #211).

Admission runs `verify` and nothing else, so what it asserts *is* the kit's definition of a
good demo. This file pinned that definition against a canned project served **twice** while
the seam had two arms — once as a deprecated-API Langfuse and once as a v4 one — and
required an identical verdict, which was #211's acceptance criterion. It was identical, and
that is what let #213 delete the deprecated arm.

The canned server is v4-only now and **404s every deprecated endpoint**, so a read that
quietly stayed on one fails here rather than passing on a fallback. The fake sits at the
transport, so normalisation runs for real: v4's `subject` object, its typed score value, its
cursor pagination, its renamed cost column.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from langfuse_synth_core import read

from synth import verify as V
from synth.config import load_config
from synth.materialize import REINDEX_OFFSET_DAYS


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _today() -> date:
    return datetime.now(timezone.utc).date()


# The canned project is served relative to an as-of anchor `verify` is never told (portal
# #229): it must derive the re-index boundary from the newest data it reads. The default
# anchor is a month in the past — the "verify re-run days after seed" case; the
# parametrised tests below move it to today and to a fortnight out.
_DEFAULT_ANCHOR = datetime.combine(_today() - timedelta(days=30), datetime.min.time(),
                                   tzinfo=timezone.utc).replace(hour=12)
# Rows sit where the generator puts them: the healthy baseline well before the re-index,
# the degraded tail reaching right up to the anchor (the newest thing that landed).
PRE_TS = _iso(_DEFAULT_ANCHOR - timedelta(days=REINDEX_OFFSET_DAYS + 5))   # pre-re-index
POST_TS = _iso(_DEFAULT_ANCHOR - timedelta(hours=1))                       # post-re-index


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def _install_seeded_env(monkeypatch, *, post_relevance: float = 0.52,
                        resolutions=("self_served", "escalated"),
                        anchor: datetime | None = None) -> None:
    """Serve the canned seeded project as a v4 Langfuse — and only as one.

    `anchor` is the as-of date the canned data was "seeded" on; the rows sit on either
    side of `anchor − REINDEX_OFFSET_DAYS`. `verify` is not told it.
    """
    pre_ts, post_ts = PRE_TS, POST_TS
    if anchor is not None:
        pre_ts = _iso(anchor - timedelta(days=REINDEX_OFFSET_DAYS + 5))
        post_ts = _iso(anchor - timedelta(hours=1))

    def score_rows(name):
        if name == "retrieval_relevance":
            rows = [(pre_ts, "NUMERIC", 0.86, None), (pre_ts, "NUMERIC", 0.84, None),
                    (post_ts, "NUMERIC", post_relevance, None),
                    (post_ts, "NUMERIC", post_relevance, None)]
        elif name == "resolution":
            rows = [(post_ts, "CATEGORICAL", label, None) for label in resolutions]
        elif name == "deflected":
            rows = [(post_ts, "BOOLEAN", 1.0, "session")]
        else:
            rows = []
        out = []
        for i, (ts, dt, value, session) in enumerate(rows):
            subject = ({"kind": "session", "id": "S-1"} if session
                       else {"kind": "trace", "id": "t1"})
            out.append({"id": f"{name}-{i}", "name": name, "dataType": dt,
                        "timestamp": ts, "value": value, "subject": subject})
        return out

    generations = [{"id": "o1", "traceId": "t1", "type": "GENERATION", "name": "draft-reply",
                    "startTime": post_ts}]

    def handler(method, url, *, params=None, auth=None, timeout=30, throttle_s=0.0,
                attempts=8):
        params = params or {}
        path = url.replace("http://localhost:3000", "")

        # Every deprecated endpoint is gone from this server.
        if re.match(r"/api/public/(traces|observations|sessions|v2/scores|metrics)\b", path):
            return _Resp(404, {})

        if path == "/api/public/v2/observations":
            if params.get("type") == "GENERATION":
                rows = [{**g, "totalCost": 0.004} for g in generations]
            else:
                rows = [{"id": "root-t1", "traceId": "t1", "type": "SPAN",
                         "name": "support-triage-turn", "sessionId": "S-1",
                         "startTime": post_ts},
                        {"id": "root-t2", "traceId": "t2", "type": "SPAN",
                         "name": "support-triage-turn", "sessionId": "S-1",
                         "startTime": pre_ts}]
            return _Resp(200, {"data": rows, "meta": {}})
        if path == "/api/public/v3/scores":
            return _Resp(200, {"data": score_rows(params.get("name")), "meta": {}})

        raise AssertionError(f"unexpected read: {path!r}")

    monkeypatch.setattr(read, "request_retry", handler)


def _run() -> dict:
    report = V.run_verify(load_config("config/demo.yaml"), log=lambda _m: None)
    return {c.name: c.ok for c in report.checks}


ALL_CHECKS = {
    "traces_present", "sessions_grouped", "retrieval_relevance_present",
    "retrieval_regression_visible", "post_reindex_breaches_floor",
    "both_resolutions_present", "session_deflection_scored",
    "generation_cost_attributed",
}


def test_a_healthy_seeded_project_passes_every_check(monkeypatch):
    _install_seeded_env(monkeypatch)
    checks = _run()
    assert set(checks) == ALL_CHECKS
    assert all(checks.values()), f"unexpected failures: {[k for k, v in checks.items() if not v]}"


def test_a_regression_that_did_not_land_fails_the_oracle(monkeypatch):
    """The story, not the row count: scores on both sides of the boundary with no drop
    between them is a seeded pool that no longer tells the demo's story."""
    _install_seeded_env(monkeypatch, post_relevance=0.85)
    checks = _run()
    assert checks["retrieval_regression_visible"] is False
    assert checks["post_reindex_breaches_floor"] is False
    assert checks["traces_present"] and checks["retrieval_relevance_present"]


def test_one_sided_resolutions_fail_the_oracle(monkeypatch):
    """A categorical score reads by its **label**. Reading it as a number would quietly pass
    this check with no labels at all — the trap the deprecated API set by sending `value: 0`
    beside a `stringValue`, and one the seam still guards against on the v3 shape."""
    _install_seeded_env(monkeypatch, resolutions=("self_served",))
    assert _run()["both_resolutions_present"] is False


def test_verify_names_no_deprecated_endpoint_itself(monkeypatch):
    """The seam is the only place this kit reaches Langfuse, so `verify` naming an endpoint
    at all would be the thing #211 exists to prevent — and #213 makes it a live failure
    rather than future debt, since the endpoints it would name have no successor here."""
    body = "\n".join(line for line in pathlib.Path("src/synth/verify.py")
                      .read_text(encoding="utf-8").splitlines()
                      if not line.lstrip().startswith("#"))
    body = body.split('"""', 2)[-1]           # the docstring discusses the migration
    for retired in ("/api/public/traces", "/api/public/observations",
                    "/api/public/v2/scores", "/api/public/sessions"):
        assert retired not in body, retired


def test_verify_names_the_v4_read_apis_in_its_log(monkeypatch):
    _install_seeded_env(monkeypatch)
    lines: list[str] = []
    V.run_verify(load_config("config/demo.yaml"), log=lines.append)
    assert any("v4 read APIs" in line for line in lines), lines


# --- the boundary is derived from the data, not told (portal #229) -----------------------
@pytest.mark.parametrize("anchor_day", [
    pytest.param(_today(), id="as-of-today"),
    pytest.param(_today() + timedelta(days=14), id="as-of-a-fortnight-out"),
    pytest.param(_today() - timedelta(days=30), id="verify-re-run-a-month-after-seed"),
])
def test_boundary_checks_pass_whatever_day_the_data_was_seeded_on(monkeypatch, anchor_day):
    """`verify` is never handed the as-of date: it takes the newest observed timestamp as
    the run-date proxy and subtracts the generator's offset. So the two boundary checks
    pass for a pool seeded as of today, one tethered a fortnight into the future, and one
    verified long after its seed — the case that rules out recomputing `now − offset`."""
    anchor = datetime.combine(anchor_day, datetime.min.time(), tzinfo=timezone.utc)
    _install_seeded_env(monkeypatch, anchor=anchor.replace(hour=12))
    checks = _run()
    assert checks["retrieval_regression_visible"] is True
    assert checks["post_reindex_breaches_floor"] is True


def test_verify_reads_no_clock_and_no_seed_constant():
    """The boundary must come from the data: no wall clock (wrong on a re-run days later),
    no anchor imported from the generator (that would replay seed's own assumption)."""
    body = "\n".join(line for line in pathlib.Path("src/synth/verify.py")
                      .read_text(encoding="utf-8").splitlines()
                      if not line.lstrip().startswith("#"))
    body = body.split('"""', 2)[-1]
    for forbidden in ("REINDEX_AT", "RUN_DATE", "now_utc", "datetime.now", "date.today"):
        assert forbidden not in body, forbidden


def test_no_timestamped_data_is_a_failed_check_not_a_crash(monkeypatch):
    _install_seeded_env(monkeypatch)
    def empty(*_a, **_k):
        return []

    monkeypatch.setattr(read.LangfuseReader, "scores", empty)
    monkeypatch.setattr(read.LangfuseReader, "traces", empty)
    checks = _run()
    assert checks["retrieval_regression_visible"] is False
