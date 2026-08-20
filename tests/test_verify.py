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


def _install_seeded_env(monkeypatch, *, post_relevance: float = 0.52,
                        resolutions=("self_served", "escalated")) -> None:
    """Serve the canned seeded project as a v4 Langfuse — and only as one."""
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
            subject = ({"kind": "session", "id": "S-1"} if session
                       else {"kind": "trace", "id": "t1"})
            out.append({"id": f"{name}-{i}", "name": name, "dataType": dt,
                        "timestamp": ts, "value": value, "subject": subject})
        return out

    generations = [{"id": "o1", "traceId": "t1", "type": "GENERATION", "name": "draft-reply",
                    "startTime": POST_TS}]

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
                         "startTime": POST_TS},
                        {"id": "root-t2", "traceId": "t2", "type": "SPAN",
                         "name": "support-triage-turn", "sessionId": "S-1",
                         "startTime": PRE_TS}]
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
