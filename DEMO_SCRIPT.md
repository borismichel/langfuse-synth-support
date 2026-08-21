# Presenter Runbook — Support Triage Deflection Decay

The `render: markdown` artifact declared in `usecase.yaml`. `synth seed` publishes a copy
into the container's `/app/out/` so the portal collects it after the step exits.

**Runtime:** about 12 minutes for the core walk, 18 with the live console.

---

## 1. What this demo shows

A support-triage agent was quietly ruined by a maintenance job.

The agent handles customer tickets end to end — classify the intent, search the knowledge
base, draft a reply, and hand off to a human only when it cannot stand behind the answer.
It worked. Then someone re-indexed the knowledge base. The new index dropped article titles
and a shifted chunk boundary orphaned each article's opening paragraph — the part that
actually answers the question.

Nothing broke. No exception, no failed request, no alert. Retrieval just got worse:
top-chunk relevance fell from ~0.82 to ~0.54, the agent started retrying its searches,
context grew, and escalations to human agents went from ~5% to ~44%. The support team felt
it as "we're busier than we used to be." The dashboard that would have caught it — error
rate — was flat and green the entire time.

**This is the demo:** a failure that is invisible to conventional monitoring and obvious
in Langfuse. It lands tracing, sessions, cost tracking, scores, and user feedback.

## 2. Setup

- Deploy the kit. The pipeline runs `synth seed` (generate + ingest) then `synth verify`.
- Volume knob: **Target traces** (`generation.target_traces`) — the single operator
  control. 2,000 gives a convincing 28-day picture; 500 is enough for a short session.
- The data covers a 28-day window. The re-index lands 10 days before the end, so the
  charts have a long healthy baseline and a clear degraded tail.
- If the Companion is enabled, open it in a second tab before you start. You will use it
  in beat 5.

## 3. Walk the story

### Beat 1 — "Everything is fine" (2 min)

Open **Tracing** and show the volume: thousands of traces, every one of them successful.
Filter on errors — nothing. Point out that this is the entire picture most teams have, and
on this evidence there is no incident to investigate.

> The support lead's complaint is not "it's broken." It's "the bots aren't helping as much
> as they used to." That is not something an error rate can answer.

### Beat 2 — The metric that actually moved (3 min)

Chart the **`deflected`** score over time. This is a *session*-level score — one per
ticket, not per turn — because "did we resolve this without a human" is a property of the
whole conversation, not of any single message.

The curve is flat around 91%, then steps down to around 43% and stays there. Ten days ago.

Ask the room what changed ten days ago. Nobody knows yet — that is the point.

### Beat 3 — Find the cause in a single trace (4 min)

Filter traces to `kb-v2` and open one that escalated. Walk the tree:

```
support-triage-turn
└─ triage-agent            [agent]      — encloses the whole turn
   ├─ classify-intent      GENERATION   — fine, cheap, correct
   ├─ kb-search            [retriever]  — top_score 0.52  ← here
   ├─ kb-search            [retriever]  — retry, 0.46
   ├─ draft-reply          GENERATION   — 3x the context of a healthy turn
   └─ escalate-to-human    [tool]       — WARNING: below confidence floor
```

**A presenter's note on those labels.** Since the OTLP cutover (portal #210) the
bracketed steps land as **native** Langfuse agent-graph types — `AGENT`, `RETRIEVER`,
`TOOL` — with their type badge in the UI. Point at the badges: the agent graph is now
something Langfuse *shows*, not something the presenter narrates from metadata.

The `retrieval_relevance` score sits on the **retriever observation**, not on the trace —
so the number is attached to the step that produced it. Open that span's metadata and show
`kb_index_version: kb-v2` next to the RETRIEVER badge.

Now open a `kb-v1` trace beside it: one retrieval round, `top_score` around 0.85, no
handoff. Same agent, same prompt, same model. The only difference is the index.

**That is the diagnosis, and it took two traces.**

### Beat 4 — Put a number on it (3 min)

Two charts land the business case:

1. **`retrieval_relevance` over time** — the step change at the re-index. This is the
   cause.
2. **Cost per turn over time** — up about 29%. The agent is not failing more expensively
   by accident: worse retrieval means more rounds, more chunks, more input tokens on the
   expensive drafting model. Break cost down by model to show the cheap classifier is
   unchanged and the drafter is doing all the damage.

Then **`user_feedback`**: thumbs-up drops from ~83% to ~49%. Note how sparse it is —
roughly one turn in five gets any feedback at all, and unhappy users answer more often.
That is exactly why you cannot run quality off user feedback alone, and why the automated
`groundedness` and `retrieval_relevance` scores matter.

Optional, if the room is technical: open **Sessions** and replay a two-turn ticket where
the customer rephrases, gets a second bad answer, and gets handed off.

### Beat 5 — Break it live (5 min, needs the Companion)

Open the **live triage console**. This is not a recording — it runs the real agent against
a real (small) knowledge base and writes a real trace into this same project. The console
is multi-turn: everything you type stays in **one ticket**, which is one Langfuse session.

1. Ask it something ordinary: *"I was charged twice for my order, can I get a refund?"*
   Leave the index on `kb-v1`. It answers correctly. Relevance ~1.0, resolved.
2. Change **nothing** except the index — switch to `kb-v2` — and ask a follow-up the way a
   real customer would: *"that didn't answer it — I was double-charged, where's my money?"*
   The search now returns the *wrong article* (a returns policy, for a billing question),
   relevance collapses, and the agent hands off.
3. Point at the ticket header: it now reads **handed off to a human**. The `deflected`
   score is a property of the *whole ticket*, not the last message — one bad turn is enough
   to cost you the deflection, which is exactly why the seeded curve moved.
4. Click through to the trace, then open the **session** it belongs to. Both turns are
   there, in order, in the same project as the 28 days of history — created seconds ago.

> The lesson to land: the failure was never in the model or the prompt. It was in the
> retrieval step, and it was only ever visible to someone who could see inside the trace.

### Beat 6 — The close (1 min)

Three sentences:

- The error rate never moved, so conventional monitoring had nothing to say.
- The evidence was in the traces the whole time — a scored retrieval step and a
  session-level outcome.
- Cost and deflection put it in the language the business funds work in: **+29% spend per
  turn, and a 49-point drop in the share of tickets handled without a human** (91% → 43%).

## 4. Questions you will get

**"Is the data real?"** No — it is synthetic and deterministic. The same seed and target
trace count reproduce this pool byte for byte, which is what makes the demo repeatable. No
model is called to generate it (a gate enforces that). The *live console* in beat 5 does
call a real model.

**"Would a judge have caught this?"** Yes, and that is a good follow-on conversation:
`groundedness` here is seeded, but in production it would be an LLM-as-a-judge evaluator
running on live traces, which is what turns this from a post-mortem into an alert.

**"Why didn't latency alerts catch it?"** Latency did rise — mean turn duration goes from
about 2.8s to about 3.4s — but that is well inside the band a support tool would alert on.
Show the latency chart if pressed: the signal is there and it is weak, which is a fair
reflection of reality.

## 5. Reset

Langfuse ingestion is append-only; teardown is project-level. Delete the Langfuse project
(or create a fresh one) and re-deploy. Do **not** re-seed a project that already holds this
demo: generation is deterministic, but OTLP appends rather than upserting, so the story
would be told twice. `import-spool` refuses a second run rather than doubling it.

Note that live console runs are tagged `live` and land in `LIVE-*` sessions, so you can
filter them out of the seeded pool (or find them again) with a tag filter.
