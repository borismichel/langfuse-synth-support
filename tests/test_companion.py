"""The live triage console — routed, rendered, and emitting the right trace shape.

The determinism gate covers the seeded pool; nothing covers the companion, so these tests
stand in for it. They drive the real `create_app` against a fake Adapter, so no key, no
model, and no Langfuse instance are involved: the Adapter is exactly the seam that makes
that substitution possible.

What is worth asserting here is the demo's load-bearing claim — that flipping the index to
`kb-v2` degrades retrieval enough to force an escalation — the trace shape the seeded pool
and the console must keep in common, and the multi-turn session semantics: history reaches
the model, and the ticket's `deflected` outcome spans every turn under one stable score id.
"""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None
    or importlib.util.find_spec("starlette") is None,
    reason="companion extra (fastapi/starlette) not installed",
)

GOOD_QUESTION = "I was charged twice for my order, can I get a refund?"
BAD_QUESTION = "my two factor device is lost, how do I get back in"


class _StubLLM:
    model = "stub-model-v1"

    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    def complete(self, *, system, messages, temperature=0, max_tokens=512):
        from langfuse_synth_core.companion.llm import ChatResult

        self._calls.append({"system": system, "messages": messages,
                            "max_tokens": max_tokens})
        # One-word answer for the classifier, a sentence for the drafter.
        text = "billing" if max_tokens <= 8 else "Thanks — here is what I found."
        return ChatResult(text, 120, 20)


class _RecordingSpan:
    """One observation the seam opened, with the fields it was given."""

    def __init__(self, recorder, kw, parent=None):
        self.recorder = recorder
        self.kw = dict(kw)
        self.parent = parent
        self.trace_id = "trace-live"
        self.id = f"obs-{len(recorder.spans)}"
        recorder.spans.append(self)

    @property
    def name(self):
        return self.kw.get("name")

    @property
    def as_type(self):
        return str(self.kw.get("as_type", "span")).lower()

    def update(self, **kw):
        self.kw.update(kw)
        return self

    @contextmanager
    def start_as_current_observation(self, **kw):
        yield _RecordingSpan(self.recorder, kw, parent=self)


class _RecordingClient:
    """Stands in for the Langfuse SDK behind the live-emission seam.

    The console emits through `adapter.emitter()` since the read/live-seam cutover (portal
    #211), so the assertion surface is the observations and scores the seam opened rather
    than the Spool envelopes it used to build.
    """

    def __init__(self) -> None:
        self.spans: list[_RecordingSpan] = []
        self.scores: list[dict] = []
        self.propagated: list[dict] = []
        self.flushes = 0

    @contextmanager
    def start_as_current_observation(self, **kw):
        yield _RecordingSpan(self, kw, parent=None)

    def create_score(self, **kw):
        self.scores.append(kw)

    def flush(self):
        self.flushes += 1


class _FakeAdapter:
    """Everything `create_app` is allowed to ask the Adapter for, and nothing more."""

    base_url = "http://langfuse.test"

    def __init__(self) -> None:
        self.recorder = _RecordingClient()
        self.llm_calls: list[dict] = []

    def llm(self, model=None):
        return _StubLLM(self.llm_calls)

    def emitter(self, **kw):
        from langfuse_synth_core.live.emit import LiveEmitter

        @contextmanager
        def _propagate(**attrs):
            self.recorder.propagated.append(attrs)
            yield

        return LiveEmitter(self.base_url, public_key="pk", secret_key="sk",
                           client=self.recorder, propagate=_propagate, **kw)

    def read_json(self, path, params=None, *, throttle=0.0):
        raise RuntimeError("no Langfuse in tests — the page must fall back to the trace id")

    # -- assertion helpers ---------------------------------------------------------------

    @property
    def emitted(self) -> list:
        """Anything at all reached Langfuse — used by the "nothing was emitted" checks."""
        return self.recorder.spans + self.recorder.scores

    def scores(self, name: str) -> list[dict]:
        return [s for s in self.recorder.scores if s["name"] == name]

    def envelopes(self, name: str) -> list[str]:
        return [s["score_id"] for s in self.scores(name)]

    def spans(self) -> list[_RecordingSpan]:
        """The observations in emission order."""
        return list(self.recorder.spans)

    def traces(self) -> list[dict]:
        """The trace-level attributes propagated across each trace, in order."""
        return list(self.recorder.propagated)

    @property
    def draft_calls(self) -> list[dict]:
        return [c for c in self.llm_calls if c["max_tokens"] > 8]


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
    assert adapter.llm_calls == []


def test_healthy_index_resolves_and_broken_index_escalates(client_and_adapter):
    """The load-bearing claim: same question, different index, different outcome."""
    client, _ = client_and_adapter

    good = _post(client, index_version="kb-v1", session_id="LIVE-GOOD")
    assert "Resolved by the agent" in good.text
    assert "Escalated to a human" not in good.text

    bad = _post(client, index_version="kb-v2", session_id="LIVE-BAD")
    assert "Escalated to a human" in bad.text


def test_emitted_trace_matches_the_seeded_shape(client_and_adapter):
    client, adapter = client_and_adapter
    _post(client, index_version="kb-v1")

    spans = adapter.spans()

    # Under v4 there is no trace entity: the trace is its root observation, and its
    # correlating attributes are propagated across everything nested inside it.
    roots = [s for s in spans if s.name == "support-triage-turn"]
    assert len(roots) == 1
    trace_attrs = adapter.traces()[0]
    assert trace_attrs["session_id"] == "LIVE-TEST"
    assert trace_attrs["metadata"]["turn"] == 1
    assert "live" in trace_attrs["tags"]

    # Same observation vocabulary as the seeded pool.
    by_type: dict[str, set[str]] = {}
    for s in spans[1:]:
        by_type.setdefault(s.as_type, set()).add(s.name)
    assert by_type.get("generation") == {"classify-intent", "draft-reply"}
    assert "agent" in by_type and "retriever" in by_type

    scores = {s["name"]: s for s in adapter.recorder.scores}
    assert {"retrieval_relevance", "groundedness", "resolution", "deflected"} <= set(scores)
    # The retrieval score belongs to the retriever observation, not the trace.
    assert scores["retrieval_relevance"].get("observation_id")
    # The headline metric is session-scoped, per the scores data model.
    assert scores["deflected"]["session_id"] == "LIVE-TEST"
    assert scores["deflected"]["value"] == 1


def test_the_turn_is_delivered_before_the_console_answers(client_and_adapter):
    """The page hands the user a deep link the moment it renders, so the trace has to be on
    its way by then — the seam flushes when the trace block ends, and the session score is
    flushed behind it."""
    client, adapter = client_and_adapter
    _post(client)
    assert adapter.recorder.flushes >= 1


def test_escalation_emits_the_handoff_tool_and_flips_deflection(client_and_adapter):
    client, adapter = client_and_adapter
    _post(client, index_version="kb-v2")

    handoff = [s for s in adapter.spans() if s.name == "escalate-to-human"]
    assert len(handoff) == 1
    assert handoff[0].as_type == "tool"
    assert handoff[0].kw["level"] == "WARNING"

    assert adapter.scores("deflected")[0]["value"] == 0


def test_unresolvable_project_falls_back_to_the_trace_id(client_and_adapter):
    """`read_json` raising must not break the page — it just loses the deep link."""
    client, _ = client_and_adapter
    resp = _post(client)
    assert resp.status_code == 200
    assert "trace id" in resp.text
    assert "/traces/" not in resp.text


# --------------------------------------------------------------------------------------
# multi-turn: the ticket, not the message, is the unit of outcome
# --------------------------------------------------------------------------------------


def test_prior_turns_are_replayed_to_the_drafter(client_and_adapter):
    client, adapter = client_and_adapter

    _post(client, question="I was charged twice", session_id="LIVE-CHAT")
    _post(client, question="when will the refund land?", session_id="LIVE-CHAT")

    first, second = adapter.draft_calls
    # Turn 1 sees only its own question.
    assert len(first["messages"]) == 1
    # Turn 2 replays the prior exchange, then asks the new question.
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][0]["content"] == "I was charged twice"
    assert "when will the refund land?" in second["messages"][2]["content"]

    # The classifier stays history-free so it doesn't grow with the ticket.
    classify_calls = [c for c in adapter.llm_calls if c["max_tokens"] <= 8]
    assert all(len(c["messages"]) == 1 for c in classify_calls)


def test_turn_numbers_increment_within_a_session(client_and_adapter):
    client, adapter = client_and_adapter

    _post(client, session_id="LIVE-CHAT")
    _post(client, question="still broken", session_id="LIVE-CHAT")

    assert [t["metadata"]["turn"] for t in adapter.traces()] == [1, 2]


def test_one_bad_turn_makes_the_whole_ticket_undeflected(client_and_adapter):
    """Deflection is a property of the ticket: one handoff and the ticket is not deflected."""
    client, adapter = client_and_adapter

    _post(client, index_version="kb-v1", session_id="LIVE-CHAT")
    assert adapter.scores("deflected")[-1]["value"] == 1

    _post(client, question=BAD_QUESTION, index_version="kb-v2", session_id="LIVE-CHAT")
    assert adapter.scores("deflected")[-1]["value"] == 0

    # A third, healthy turn must NOT flip it back — a human was already involved.
    _post(client, index_version="kb-v1", session_id="LIVE-CHAT")
    assert adapter.scores("deflected")[-1]["value"] == 0


def test_session_score_keeps_one_stable_id_across_turns(client_and_adapter):
    """Re-emitting under a stable id upserts the ticket's verdict instead of piling up."""
    client, adapter = client_and_adapter

    _post(client, session_id="LIVE-CHAT")
    _post(client, question="still broken", session_id="LIVE-CHAT")

    envelope_ids = set(adapter.envelopes("deflected"))
    assert len(adapter.scores("deflected")) == 2  # emitted once per turn
    assert len(envelope_ids) == 1                 # ...but always the same score


def test_sessions_do_not_share_history(client_and_adapter):
    client, adapter = client_and_adapter

    _post(client, question="first ticket", session_id="LIVE-A")
    _post(client, question="second ticket", session_id="LIVE-B")

    # The second ticket starts clean — no replay of the first.
    assert len(adapter.draft_calls[1]["messages"]) == 1
    assert {s["session_id"] for s in adapter.scores("deflected")} == {"LIVE-A", "LIVE-B"}


def test_new_ticket_link_starts_a_fresh_session(client_and_adapter):
    client, _ = client_and_adapter
    first = client.get("/").text
    second = client.get("/").text
    # Each visit to / mints a new ticket id, so "start a new ticket" really does.
    assert first != second
