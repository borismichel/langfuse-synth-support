"""Companion requests delivered through the real SDK to controlled export/HTTP sinks.

Only the model and Langfuse network are substituted. Project ingestion and eventual
read-back remain release-image rehearsal gates, not claims made by this offline test.
"""
from __future__ import annotations

import json
import uuid

import httpx
from fastapi.testclient import TestClient
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from langfuse_synth_core.companion.llm import ChatResult
from langfuse_synth_core.live.emit import LiveEmitter
from synth.companion.app import create_app


QUESTION = "I was charged twice for my order, can I get a refund?"


class _Model:
    model = "controlled-support-model"

    def __init__(self):
        self.drafts = []

    def complete(self, *, system, messages, max_tokens):
        if max_tokens <= 8:
            return ChatResult("billing", 12, 1)
        self.drafts.append(messages)
        return ChatResult("Your refund will arrive in five working days.", 120, 20)


class _Adapter:
    base_url = "http://support-sdk.test"

    def __init__(self, sdk):
        self.sdk = sdk
        self.model = _Model()

    def llm(self):
        return self.model

    def emitter(self):
        return LiveEmitter(self.base_url, client=self.sdk, environment="support-test")

    def read_json(self, path, params=None, *, throttle=0.0):
        assert path == "/api/public/projects"
        return {"data": [{"id": "support-project"}]}


def test_multiturn_conversation_exports_typed_context_and_delivers_score_subjects(caplog):
    exported = InMemorySpanExporter()
    scores = []
    unexpected = []

    def receive(request):
        if request.method == "POST" and request.url.path == "/api/public/scores":
            scores.extend(json.loads(request.content))
            return httpx.Response(202, json={"message": "Accepted"})
        unexpected.append((request.method, request.url.path))
        return httpx.Response(404, json={"message": "Unexpected request"})

    sdk = Langfuse(
        base_url=_Adapter.base_url, public_key=f"pk-support-{uuid.uuid4()}",
        secret_key="sk-controlled", span_exporter=exported,
        httpx_client=httpx.Client(transport=httpx.MockTransport(receive)),
        flush_at=1000, flush_interval=0.05,
    )
    adapter = _Adapter(sdk)
    try:
        with TestClient(create_app(adapter)) as client:
            for index, verdict in [
                ("kb-v1", "Resolved by the agent"),
                ("kb-v2", "Escalated to a human"),
                ("kb-v1", "Resolved by the agent"),
            ]:
                response = client.post("/triage", data={
                    "question": QUESTION, "index_version": index, "session_id": "SDK-TICKET",
                })
                assert response.status_code == 200
                assert verdict in response.text
                # The route flushes before returning; scores must already have reached HTTP.
                assert len(scores) == 4 * len(adapter.model.drafts)
            response = client.post("/triage", data={
                "question": QUESTION, "index_version": "kb-v1", "session_id": "SDK-OTHER",
            })
            assert "Resolved by the agent" in response.text
            assert len(scores) == 16
        assert unexpected == []
        assert not [record.message for record in caplog.records
                    if record.name.startswith("langfuse") and record.levelno >= 30]

        spans = exported.get_finished_spans()
        roots = [span for span in spans if span.name == "support-triage-turn"]
        assert len(roots) == 4
        assert len({span.context.trace_id for span in roots}) == 4
        for root, turn, index, session, escalated in zip(
            roots, [1, 2, 3, 1], ["kb-v1", "kb-v2", "kb-v1", "kb-v1"],
            ["SDK-TICKET", "SDK-TICKET", "SDK-TICKET", "SDK-OTHER"],
            [False, True, False, False], strict=True,
        ):
            attributes = root.attributes
            assert json.loads(attributes["langfuse.observation.input"]) == {
                "ticket": session, "question": QUESTION,
            }
            assert json.loads(attributes["langfuse.observation.output"]) == {"escalated": escalated}
            assert json.loads(attributes["langfuse.observation.metadata.intent"]) == "billing"
            assert json.loads(attributes["langfuse.observation.metadata.turn"]) == turn
            assert json.loads(attributes["langfuse.observation.metadata.post_reindex"]) is escalated
            trace_spans = {span.name: span for span in spans
                           if span.context.trace_id == root.context.trace_id}
            agent = trace_spans["triage-agent"]
            assert agent.parent.span_id == root.context.span_id
            for name, span in trace_spans.items():
                attrs = span.attributes
                assert attrs["session.id"] == session
                assert attrs["user.id"] == "companion-console"
                assert attrs["langfuse.environment"] == "support-test"
                assert list(attrs["langfuse.trace.tags"]) == ["support", "triage", "live", index]
                assert json.loads(attrs["langfuse.trace.metadata.turn"]) == turn
                assert json.loads(attrs["langfuse.trace.metadata.post_reindex"]) is escalated
                if name not in {"support-triage-turn", "triage-agent"}:
                    assert span.parent.span_id == agent.context.span_id
            for name, usage in [("classify-intent", {"input": 12, "output": 1, "total": 13}),
                                ("draft-reply", {"input": 120, "output": 20, "total": 140})]:
                attrs = trace_spans[name].attributes
                assert attrs["langfuse.observation.model.name"] == "controlled-support-model"
                assert json.loads(attrs["langfuse.observation.usage_details"]) == usage
            draft = trace_spans["draft-reply"].attributes
            assert json.loads(draft["langfuse.observation.input"])["history_turns"] == turn - 1
            assert json.loads(draft["langfuse.observation.output"]) == {
                "reply": "Your refund will arrive in five working days.", "escalate": escalated,
            }
            if escalated:
                handoff = trace_spans["escalate-to-human"].attributes
                assert json.loads(handoff["langfuse.observation.output"]) == {
                    "ticket": session, "queued": True,
                }
            else:
                assert "escalate-to-human" not in trace_spans

            trace_scores = {score["name"]: score for score in scores
                            if score.get("traceId") == f"{root.context.trace_id:032x}"}
            assert set(trace_scores) == {"retrieval_relevance", "groundedness", "resolution"}
            for name in ("retrieval_relevance", "groundedness", "resolution"):
                if name == "retrieval_relevance":
                    subject = trace_spans["kb-search"]
                    assert trace_scores[name]["observationId"] == f"{subject.context.span_id:016x}"
                else:
                    # These configured scores describe the whole trace, not one child.
                    assert not trace_scores[name].get("observationId")
                assert not trace_scores[name].get("sessionId")
            assert trace_scores["retrieval_relevance"]["dataType"] == "NUMERIC"
            assert trace_scores["groundedness"]["dataType"] == "NUMERIC"
            assert trace_scores["resolution"]["dataType"] == "CATEGORICAL"
            assert trace_scores["resolution"]["value"] == (
                "escalated" if escalated else "self_served")

        session_scores = [score for score in scores if score["name"] == "deflected"]
        assert [score["value"] for score in session_scores] == [1, 0, 0, 1]
        assert len({score["id"] for score in session_scores[:3]}) == 1
        assert session_scores[3]["id"] != session_scores[0]["id"]
        assert [score["sessionId"] for score in session_scores] == [
            "SDK-TICKET", "SDK-TICKET", "SDK-TICKET", "SDK-OTHER"]
        assert all(score["dataType"] == "BOOLEAN" for score in session_scores)
        assert all(not score.get("traceId") and not score.get("observationId")
                   for score in session_scores)
        assert all(score["environment"] == "support-test" for score in scores)
        assert [message["role"] for message in adapter.model.drafts[1]] == [
            "user", "assistant", "user"]
        assert adapter.model.drafts[1][0]["content"] == QUESTION
        assert len(adapter.model.drafts[3]) == 1
    finally:
        sdk.shutdown()
