"""`verify` — this kit's sole scenario oracle — reads through the seam (portal #211).

Admission runs `verify` and nothing else, so what it asserts *is* the kit's definition of a
good demo. This file pins that definition against a canned seeded project served **twice**,
once as a deprecated-API Langfuse and once as a v4 one, and requires the verdict to be
identical: the acceptance criterion "every assertion is still made after the remap", and
"target detection recognises a v4 host", stated as tests rather than as claims.

Nothing below configures a generation. The seam probes the target — one deprecated endpoint,
and a `404` means it has cut over — so the arm is reached by what the canned server answers.
The fake sits at the transport, so normalisation runs for real: v4's `subject` object, its
typed score value, its cursor pagination, its renamed cost column.
"""
from __future__ import annotations

import pytest

from langfuse_synth_core import read

from synth import verify as V
from synth.config import load_config

PRE_TS = "2026-07-10T12:00:00.000Z"    # < REINDEX_AT
POST_TS = "2026-07-25T12:00:00.000Z"   # >= REINDEX_AT


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


def _install_seeded_env(monkeypatch, *, generation: str, post_relevance: float = 0.52,
                        resolutions=("self_served", "escalated")) -> None:
    """Serve the canned seeded project as `generation` would — and only as it would."""
    legacy = generation == read.LEGACY

    def score_rows(name):
        if name == "retrieval_relevance":
            rows = [(PRE_TS, "NUMERIC", 0.86, None), (PRE_TS, "NUMERIC", 0.84, None),
                    (POST_TS, "NUMERIC", post_relevance, None),
                    (POST_TS, "NUMERIC", post_relevance, None)]
        elif name == "resolution":
            rows = [(POST_TS, "CATEGORICAL", label, None) for label in resolutions]
        elif name == "deflected":
            rows = [(POST_TS, "BOOLEAN", 1.0, "session")]
        else:
            rows = []
        out = []
        for i, (ts, dt, value, session) in enumerate(rows):
            if legacy:
                out.append({"id": f"{name}-{i}", "name": name, "dataType": dt,
                            "timestamp": ts,
                            "value": value if dt != "CATEGORICAL" else 0,
                            "stringValue": value if dt == "CATEGORICAL" else None,
                            "traceId": "t1", "sessionId": "S-1" if session else None})
            else:
                subject = ({"kind": "session", "id": "S-1"} if session
                           else {"kind": "trace", "id": "t1"})
                out.append({"id": f"{name}-{i}", "name": name, "dataType": dt,
                            "timestamp": ts, "value": value, "subject": subject})
        return out

    generations = [{"id": "o1", "traceId": "t1", "type": "GENERATION", "name": "draft-reply",
                    "startTime": POST_TS}]

    def handler(method, url, *, params=None, auth=None, timeout=30, throttle_s=0.0):
        params = params or {}
        path = url.replace("http://localhost:3000", "")

        if path == "/api/public/traces":                 # the probe, and the legacy list
            if not legacy:
                return _Resp(404, {})
            return _Resp(200, {"data": [
                {"id": "t1", "sessionId": "S-1", "timestamp": POST_TS},
                {"id": "t2", "sessionId": "S-1", "timestamp": PRE_TS},
            ], "meta": {"totalPages": 1}})
        if path == "/api/public/observations":
            if not legacy:
                return _Resp(404, {})
            rows = [{**g, "calculatedTotalCost": 0.004} for g in generations]
            return _Resp(200, {"data": rows, "meta": {"totalPages": 1}})
        if path == "/api/public/v2/scores":
            if not legacy:
                return _Resp(404, {})
            return _Resp(200, {"data": score_rows(params.get("name")),
                               "meta": {"totalPages": 1}})

        if path == "/api/public/v2/observations":
            if legacy:
                return _Resp(404, {})
            if params.get("type") == "GENERATION":
                rows = [{**g, "totalCost": 0.004} for g in generations]
            else:
                rows = [{"id": "root-t1", "traceId": "t1", "type": "SPAN",
                         "name": "support-triage-turn", "sessionId": "S-1",
                         "startTime": POST_TS},
                        {"id": "root-t2", "traceId": "t2", "type": "SPAN",
                         "name": "support-triage-turn", "sessionId": "S-1",
                         "startTime": PRE_TS}]
            return _Resp(200, {"data": rows, "meta": {}})
        if path == "/api/public/v3/scores":
            if legacy:
                return _Resp(404, {})
            return _Resp(200, {"data": score_rows(params.get("name")), "meta": {}})

        raise AssertionError(f"unexpected read: {path!r} (generation={generation})")

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


@pytest.mark.parametrize("generation", [read.LEGACY, read.V4])
def test_a_healthy_seeded_project_passes_every_check(monkeypatch, generation):
    _install_seeded_env(monkeypatch, generation=generation)
    checks = _run()
    assert set(checks) == ALL_CHECKS
    assert all(checks.values()), f"unexpected failures: {[k for k, v in checks.items() if not v]}"


@pytest.mark.parametrize("generation", [read.LEGACY, read.V4])
def test_a_regression_that_did_not_land_fails_the_oracle(monkeypatch, generation):
    """The story, not the row count: scores on both sides of the boundary with no drop
    between them is a seeded pool that no longer tells the demo's story."""
    _install_seeded_env(monkeypatch, generation=generation, post_relevance=0.85)
    checks = _run()
    assert checks["retrieval_regression_visible"] is False
    assert checks["post_reindex_breaches_floor"] is False
    assert checks["traces_present"] and checks["retrieval_relevance_present"]


@pytest.mark.parametrize("generation", [read.LEGACY, read.V4])
def test_one_sided_resolutions_fail_the_oracle(monkeypatch, generation):
    """A categorical score reads by its label on both generations — which is the one the
    deprecated API sent as `value: 0` beside a `stringValue`. Reading it as a number would
    quietly pass this check with no labels at all."""
    _install_seeded_env(monkeypatch, generation=generation, resolutions=("self_served",))
    assert _run()["both_resolutions_present"] is False


def test_the_verdict_is_identical_on_both_generations(monkeypatch):
    _install_seeded_env(monkeypatch, generation=read.LEGACY)
    legacy = _run()
    _install_seeded_env(monkeypatch, generation=read.V4)
    assert _run() == legacy


def test_verify_recognises_a_v4_host_and_says_so(monkeypatch):
    _install_seeded_env(monkeypatch, generation=read.V4)
    lines: list[str] = []
    V.run_verify(load_config("config/demo.yaml"), log=lines.append)
    assert any("v4 read APIs" in line for line in lines), lines
