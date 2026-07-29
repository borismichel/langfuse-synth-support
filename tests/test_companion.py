"""The live triage console — routed, rendered, and emitting the right trace shape.

The determinism gate covers the seeded pool; nothing covers the companion, so these tests
stand in for it. They drive the real `create_app` against a fake Adapter, so no key, no
model, and no Langfuse instance are involved: the Adapter is exactly the seam that makes
that substitution possible.

What is worth asserting here is the demo's load-bearing claim — that flipping the index to
`kb-v2` degrades retrieval enough to force an escalation — plus the trace shape the seeded
pool and the console must keep in common.
"""
from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None
    or importlib.util.find_spec("starlette") is None,
    reason="companion extra (fastapi/starlette) not installed",
)

GOOD_QUESTION = "I was charged twice for my order, can I get a refund?"


class _StubLLM:
    model = "stub-model-v1"

    def complete(self, *, system, messages, temperature=0, max_tokens=512):
        from langfuse_synth_core.companion.llm import ChatResult

        # One-word answer for the classifier, a sentence for the drafter.
        text = "billing" if max_tokens <= 8 else "Thanks — here is what I found."
        return ChatResult(text, 120, 20)


class _StubIngestor:
    def __init__(self, sink: list[dict]) -> None:
        self._sink = sink

    def extend(self, events) -> None:
        self._sink.extend(events)

    def flush(self) -> None:  # nothing to send — the sink IS the assertion surface
        pass


class _FakeAdapter:
    """Everything `create_app` is allowed to ask the Adapter for, and nothing more."""

    base_url = "http://langfuse.test"

    def __init__(self) -> None:
        self.emitted: list[dict] = []

    def llm(self, model=None):
        return _StubLLM()

    def ingestor(self, **kw):
        return _StubIngestor(self.emitted)

    def read_json(self, path, params=None, *, throttle=0.0):
        raise RuntimeError("no Langfuse in tests — the page must fall back to the trace id")


@pytest.fixture()
def client_and_adapter():
    from fastapi.testclient import TestClient

    from synth.companion.app import create_app

    adapter = _FakeAdapter()
    return TestClient(create_app(adapter)), adapter


def _post(client, **form):
    form.setdefault("question", GOOD_QUESTION)
    form.setdefault("index_version", "kb-v1")
    form.setdefault("session_id", "LIVE-TEST")
    return client.post("/triage", data=form)


def test_console_renders(client_and_adapter):
    client, _ = client_and_adapter
    resp = client.get("/")
    assert resp.status_code == 200
    # Both index versions must be offerable, or the demo's central gesture is impossible.
    assert "kb-v1" in resp.text and "kb-v2" in resp.text


def test_empty_question_is_rejected_without_calling_the_model(client_and_adapter):
    client, adapter = client_and_adapter
    resp = _post(client, question="   ")
    assert resp.status_code == 200
    assert "Type a customer question first." in resp.text
    assert adapter.emitted == []


def test_healthy_index_resolves_and_broken_index_escalates(client_and_adapter):
    """The load-bearing claim: same question, different index, different outcome."""
    client, _ = client_and_adapter

    good = _post(client, index_version="kb-v1")
    assert "Resolved by the agent" in good.text

    bad = _post(client, index_version="kb-v2")
    assert "Escalated to a human" in bad.text


def test_emitted_trace_matches_the_seeded_shape(client_and_adapter):
    client, adapter = client_and_adapter
    _post(client, index_version="kb-v1")

    by_type: dict[str, list[dict]] = {}
    for ev in adapter.emitted:
        by_type.setdefault(ev["type"], []).append(ev["body"])

    assert len(by_type["trace-create"]) == 1
    trace = by_type["trace-create"][0]
    assert trace["name"] == "support-triage-turn"
    assert trace["sessionId"] == "LIVE-TEST"
    assert "live" in trace["tags"]

    # Same observation vocabulary as the seeded pool (rich types degrade to spans).
    names = {b["name"] for b in by_type["generation-create"]}
    assert names == {"classify-intent", "draft-reply"}
    span_types = {b["metadata"]["observation_type"] for b in by_type["span-create"]}
    assert {"agent", "retriever"} <= span_types

    scores = {b["name"]: b for b in by_type["score-create"]}
    assert {"retrieval_relevance", "groundedness", "resolution", "deflected"} <= set(scores)
    # The retrieval score belongs to the retriever observation, not the trace.
    assert scores["retrieval_relevance"].get("observationId")
    # The headline metric is session-scoped, per the scores data model.
    assert scores["deflected"]["sessionId"] == "LIVE-TEST"
    assert scores["deflected"]["value"] == 1


def test_escalation_emits_the_handoff_tool_and_flips_deflection(client_and_adapter):
    client, adapter = client_and_adapter
    _post(client, index_version="kb-v2")

    spans = [e["body"] for e in adapter.emitted if e["type"] == "span-create"]
    handoff = [s for s in spans if s["name"] == "escalate-to-human"]
    assert len(handoff) == 1
    assert handoff[0]["metadata"]["observation_type"] == "tool"
    assert handoff[0]["level"] == "WARNING"

    deflected = [
        e["body"] for e in adapter.emitted
        if e["type"] == "score-create" and e["body"]["name"] == "deflected"
    ]
    assert deflected[0]["value"] == 0


def test_unresolvable_project_falls_back_to_the_trace_id(client_and_adapter):
    """`read_json` raising must not break the page — it just loses the deep link."""
    client, _ = client_and_adapter
    resp = _post(client)
    assert resp.status_code == 200
    assert "trace id" in resp.text
    assert "/traces/" not in resp.text
