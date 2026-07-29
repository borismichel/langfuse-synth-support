"""Companion surface — the live triage console (Companion Adapter, Spec G · G3).

The seeded pool proves the regression happened over 28 days. This surface lets an SA
*cause* it on stage: type a customer question, flip the KB index between `kb-v1` and the
botched `kb-v2` re-index, and watch the same failure — relevance collapses, the retrieved
article stops being the right one, and the agent hands off to a human. Every submission
emits a **real Langfuse trace** with the same shape as the seeded pool (AGENT → RETRIEVER →
GENERATION → TOOL, plus scores), so the live run lands next to the history it explains.

The Adapter owns invocation, bind, health, shutdown, secret intake, and the ready clients;
this module only decides what the scene *is*. It never reads a raw key or env var.

Note the division of labour with `materialize.py`: the seeded pool is deterministic and
strictly model-free (a gate proves it). This surface is neither — it is live, it calls a
model, and that is allowed precisely because it is not seed runtime.
"""
from __future__ import annotations

import html
import secrets
from datetime import datetime, timezone
from typing import Any

from langfuse_synth_core.companion import CompanionAdapter, parse_invocation
from langfuse_synth_core.live import paths, theme
from langfuse_synth_core.rng import Rng
from langfuse_synth_core.seed.events import (
    generation_event,
    observation_event,
    score_event,
    trace_event,
)

from ..kb import INDEX_VERSIONS, search
from ..materialize import RELEVANCE_ESCALATION_FLOOR

# Kept in step with the `live_components` entry in usecase.yaml. HEALTH_PATH is the
# Adapter's readiness route and MUST differ from `/`.
HEALTH_PATH = "/healthz"
REQUIRES_SECRETS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LLM_API_KEY")

TOP_K = 3

SYSTEM_PROMPT = (
    "You are a customer-support triage agent. Answer ONLY from the knowledge-base extracts "
    "provided. If the extracts do not actually answer the customer's question, do not guess "
    "or improvise — reply that you are handing the ticket to a human colleague and say what "
    "is missing. Keep it to three sentences, plain and warm, no bullet points."
)
CLASSIFY_PROMPT = (
    "Classify the customer message into exactly one of: billing, technical, account, "
    "shipping. Reply with the single word and nothing else."
)

# Project ids are stable per base URL; resolved lazily for the trace deep link.
_project_id_cache: dict[str, str] = {}


class TriageResult:
    """One live triage turn: what was retrieved, what was said, and where it landed."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


# --------------------------------------------------------------------------------------
# the live agent
# --------------------------------------------------------------------------------------


def _run_triage(adapter: CompanionAdapter, question: str, index_version: str,
                session_id: str) -> TriageResult:
    """Classify → retrieve → draft → (escalate), emitting one Langfuse trace as it goes."""
    llm = adapter.llm()
    rng = Rng(secrets.randbits(63))
    trace_id = rng.trace_id("live")
    agent_id = rng.obs_id("agent")
    started = datetime.now(timezone.utc)
    events: list[dict] = []

    # -- classify ------------------------------------------------------------------------
    t0 = datetime.now(timezone.utc)
    classify = llm.complete(
        system=CLASSIFY_PROMPT,
        messages=[{"role": "user", "content": question}],
        max_tokens=8,
    )
    intent = classify.text.strip().lower().split()[0] if classify.text.strip() else "unknown"
    t1 = datetime.now(timezone.utc)
    events.append(
        generation_event(
            obs_id=rng.obs_id("classify"), trace_id=trace_id, parent_id=agent_id,
            name="classify-intent", start=t0, end=t1, model=llm.model,
            usage_details={
                "input": classify.input_tokens,
                "output": classify.output_tokens,
                "total": classify.input_tokens + classify.output_tokens,
            },
            # Empty cost_details on purpose: this is a REAL model, so Langfuse infers USD
            # from its own model definitions rather than trusting a number we made up.
            cost_details={},
            input={"message": question}, output={"intent": intent},
        )
    )

    # -- retrieve (the step the re-index broke) -------------------------------------------
    t2 = datetime.now(timezone.utc)
    hits = search(question, index_version=index_version, top_k=TOP_K)
    t3 = datetime.now(timezone.utc)
    best = hits[0].score if hits else 0.0
    retrieve_id = rng.obs_id("retrieve")
    events.append(
        observation_event(
            obs_id=retrieve_id, trace_id=trace_id, parent_id=agent_id, name="kb-search",
            obs_type="RETRIEVER", start=t2, end=t3,
            input={"query": question, "top_k": TOP_K},
            output={
                "chunks": len(hits),
                "top_score": round(best, 6),
                "articles": [h.article.id for h in hits],
            },
            metadata={"kb_index_version": index_version, "round": 1,
                      "top_score": round(best, 6)},
        )
    )
    events.append(
        score_event(
            score_id=rng.score_id("relevance"), name="retrieval_relevance",
            value=round(best, 6), data_type="NUMERIC", timestamp=t3,
            trace_id=trace_id, observation_id=retrieve_id,
        )
    )

    # -- draft ----------------------------------------------------------------------------
    context = "\n\n".join(
        f"[{h.article.id}] {h.article.title}\n{h.article.body}" for h in hits
    ) or "(the knowledge base returned nothing)"
    t4 = datetime.now(timezone.utc)
    draft = llm.complete(
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Knowledge-base extracts:\n{context}\n\nCustomer message:\n{question}",
        }],
        max_tokens=320,
    )
    t5 = datetime.now(timezone.utc)
    escalate = best < RELEVANCE_ESCALATION_FLOOR
    events.append(
        generation_event(
            obs_id=rng.obs_id("draft"), trace_id=trace_id, parent_id=agent_id,
            name="draft-reply", start=t4, end=t5, model=llm.model,
            usage_details={
                "input": draft.input_tokens,
                "output": draft.output_tokens,
                "total": draft.input_tokens + draft.output_tokens,
            },
            cost_details={},
            input={"context_chunks": len(hits), "intent": intent},
            output={"reply": draft.text, "escalate": escalate},
            metadata={"context_chunks": len(hits), "kb_index_version": index_version},
        )
    )

    # -- hand off -------------------------------------------------------------------------
    end = datetime.now(timezone.utc)
    if escalate:
        events.append(
            observation_event(
                obs_id=rng.obs_id("escalate"), trace_id=trace_id, parent_id=agent_id,
                name="escalate-to-human", obs_type="TOOL", start=t5, end=end,
                input={"queue": intent, "reason": "low_confidence"},
                output={"ticket": session_id, "queued": True},
                level="WARNING",
                status_message="handed off: retrieved context below confidence floor",
            )
        )

    # -- the trace root, the enclosing agent span, and the verdict scores ------------------
    events.insert(
        0,
        trace_event(
            trace_id=trace_id, timestamp=started, name="support-triage-turn",
            user_id="companion-console", session_id=session_id,
            tags=["support", "triage", "live", index_version],
            metadata={"intent": intent, "channel": "companion", "turn": 1,
                      "kb_index_version": index_version,
                      "post_reindex": index_version == "kb-v2"},
            input={"ticket": session_id, "question": question},
            output={"escalated": escalate},
        ),
    )
    events.append(
        observation_event(
            obs_id=agent_id, trace_id=trace_id, name="triage-agent", obs_type="AGENT",
            start=started, end=end,
            input={"question": question, "intent": intent},
            output={"escalated": escalate, "retrieval_rounds": 1},
            metadata={"kb_index_version": index_version, "retrieval_rounds": 1},
        )
    )
    events.append(
        score_event(
            score_id=rng.score_id("groundedness"), name="groundedness",
            value=round(best, 6), data_type="NUMERIC", timestamp=t5, trace_id=trace_id,
            comment="live run: share of the question covered by retrieved context",
        )
    )
    events.append(
        score_event(
            score_id=rng.score_id("resolution"), name="resolution",
            value="escalated" if escalate else "self_served",
            data_type="CATEGORICAL", timestamp=end, trace_id=trace_id,
        )
    )
    events.append(
        score_event(
            score_id=rng.score_id("deflected"), name="deflected",
            value=0 if escalate else 1, data_type="BOOLEAN", timestamp=end,
            session_id=session_id, comment="live console run",
        )
    )

    ingestor = adapter.ingestor()
    ingestor.extend(events)
    ingestor.flush()

    return TriageResult(
        question=question, index_version=index_version, intent=intent, hits=hits,
        best=best, reply=draft.text.strip(), escalate=escalate, trace_id=trace_id,
        session_id=session_id,
    )


def _trace_url(adapter: CompanionAdapter, trace_id: str) -> str | None:
    """Deep link to the trace, if the project id can be resolved for these keys.

    The trace detail route is project-scoped (`/project/{id}/traces/{traceId}`), so the
    project id has to be looked up. If that fails we return None and the page shows the raw
    trace id rather than a link that would 404.
    """
    base = adapter.base_url
    if base not in _project_id_cache:
        try:
            data = adapter.read_json("/api/public/projects").get("data") or []
            if not data:
                return None
            _project_id_cache[base] = data[0]["id"]
        except Exception:
            return None
    return f"{base}/project/{_project_id_cache[base]}/traces/{trace_id}"


# --------------------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------------------


def _new_session_id() -> str:
    return f"LIVE-{secrets.token_hex(4).upper()}"


def _console_page(*, session_id: str, question: str = "", index_version: str = "kb-v1",
                  result: TriageResult | None = None, error: str | None = None,
                  trace_url: str | None = None) -> str:
    e = html.escape
    options = "".join(
        f"<option value='{v}'{' selected' if v == index_version else ''}>"
        f"{v}{' — healthy' if v == 'kb-v1' else ' — after the re-index'}</option>"
        for v in INDEX_VERSIONS
    )
    body = [
        "<p class='eyebrow'>Live triage console</p>",
        "<h1>Break it <span class='mark'>on purpose</span>.</h1>",
        "<p class='sub'>Ask the support agent something, then switch the knowledge-base "
        "index. <code>kb-v1</code> is healthy; <code>kb-v2</code> is the botched re-index "
        "that dropped article titles and orphaned each opening paragraph. Every submission "
        "emits a real Langfuse trace into this project, alongside the seeded history.</p>",
        f"<form method='post' action='{paths.local('/triage')}'>",
        f"<input type='hidden' name='session_id' value='{e(session_id)}'>",
        "<p><textarea name='question' rows='3' style='width:100%' "
        "placeholder='e.g. I was charged twice for my order, can I get a refund?'>"
        f"{e(question)}</textarea></p>",
        f"<p><label>Knowledge-base index &nbsp;<select name='index_version'>{options}"
        "</select></label> &nbsp; <button type='submit'>Run triage</button></p>",
        "</form>",
    ]

    if error:
        body.append(f"<h2>Something went wrong</h2><p class='sub'>{e(error)}</p>")

    if result is not None:
        verdict = "Escalated to a human" if result.escalate else "Resolved by the agent"
        body += [
            "<hr>",
            f"<h2>{verdict}</h2>",
            f"<p class='sub'>intent <code>{e(result.intent)}</code> &middot; index "
            f"<code>{e(result.index_version)}</code> &middot; top relevance "
            f"<strong>{result.best:.2f}</strong> (escalation floor "
            f"{RELEVANCE_ESCALATION_FLOOR})</p>",
            f"<blockquote>{e(result.reply)}</blockquote>",
            "<h3>What the search returned</h3><ul>",
        ]
        for h in result.hits:
            body.append(
                f"<li><strong>{h.score:.2f}</strong> &middot; <code>{e(h.article.id)}</code> "
                f"{e(h.article.title)}<br><span class='sub'>{e(h.snippet)}</span></li>"
            )
        if not result.hits:
            body.append("<li class='sub'>nothing matched</li>")
        body.append("</ul>")
        if trace_url:
            body.append(
                f"<p><a class='back' href='{e(trace_url)}'>open this trace in Langfuse "
                "&rarr;</a></p>"
            )
        else:
            body.append(
                f"<p class='sub'>trace id <code>{e(result.trace_id)}</code> &middot; session "
                f"<code>{e(result.session_id)}</code></p>"
            )

    body.append(f"<p><a class='back' href='{paths.local(HEALTH_PATH)}'>readiness &rarr;</a></p>")
    return theme.page("".join(body), title="Support Triage Deflection · console")


# --------------------------------------------------------------------------------------
# the app
# --------------------------------------------------------------------------------------


def create_app(adapter: CompanionAdapter) -> Any:
    """Build the live Surface on `adapter` (its ready clients) and return a FastAPI app."""
    from fastapi import FastAPI, Form
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def _root() -> str:
        return _console_page(session_id=_new_session_id())

    @app.post("/triage", response_class=HTMLResponse)
    async def _triage(
        question: str = Form(""),
        index_version: str = Form("kb-v1"),
        session_id: str = Form(""),
    ) -> str:
        sid = session_id or _new_session_id()
        version = index_version if index_version in INDEX_VERSIONS else "kb-v1"
        if not question.strip():
            return _console_page(
                session_id=sid, index_version=version,
                error="Type a customer question first.",
            )
        try:
            result = _run_triage(adapter, question.strip(), version, sid)
        except Exception as exc:  # a live scene must never 500 in front of an audience
            return _console_page(
                session_id=sid, question=question, index_version=version,
                error=f"{type(exc).__name__}: {exc}",
            )
        return _console_page(
            session_id=sid, question=question, index_version=version,
            result=result, trace_url=_trace_url(adapter, result.trace_id),
        )

    return app


def main(argv: list[str] | None = None) -> int:
    """`synth companion --config {config} --host 0.0.0.0 --port <p>` — boot the Surface."""
    from synth.config import load_config

    inv = parse_invocation(argv)
    cfg = load_config(inv.config)
    adapter = CompanionAdapter(
        cfg, requires_secrets=REQUIRES_SECRETS, health_path=HEALTH_PATH
    )
    adapter.run(create_app, host=inv.host, port=inv.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
