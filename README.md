# Support Triage Deflection Decay

A **Demo Depot cartridge**: a knowledge-base re-index quietly halves retrieval
quality, and a support-triage agent starts handing tickets to humans that it
used to resolve on its own. Deflection falls from ~91% to ~43%, cost per turn
rises 29%, and the error rate never moves. Deployed as-is from the portal
catalog, it lands the Run-Triad — the Spool (28 days of deterministic backdated
traces), the Presenter Runbook (`DEMO_SCRIPT.md`), and a Companion (the live
triage console).

The portal serves this file as the kit's catalog **Overview** doc.

## What this demo is

A support-triage agent handles customer tickets end to end: classify the intent,
search the knowledge base, draft a reply, hand off to a human only when it cannot
stand behind the answer. It works — until the knowledge base is re-indexed. The
new index drops article titles and a shifted chunk boundary orphans each
article's opening paragraph, which is the part that answers the question.

Nothing throws. No failed request, no alert, no error-rate blip. Retrieval simply
degrades: top-chunk relevance falls from ~0.82 to ~0.54, the agent starts
retrying its searches, more context goes into the expensive drafting model, and
escalations jump from ~5% to ~44% of turns.

That is the tension the demo stages: **a failure that is invisible to
conventional monitoring and obvious in a trace.** The diagnosis takes two traces
side by side — one from before the re-index, one from after — and the business
case comes straight off the cost and deflection curves.

### What deploying lands

| | |
| --- | --- |
| **Spool** | 28 days of backdated traces across the re-index boundary. One ticket = one **session** (1–3 turns); each turn is an `AGENT` span over `classify-intent` → `kb-search` (`RETRIEVER`, one or more rounds) → `draft-reply` → optional `escalate-to-human` (`TOOL`). |
| **Scores** | `retrieval_relevance` (NUMERIC, on the retriever observation), `groundedness` and `resolution` (NUMERIC / CATEGORICAL, on the trace), `user_feedback` (BOOLEAN, sparse and skewed negative), and `deflected` (BOOLEAN, on the **session** — the headline metric). |
| **Cost** | Ingested per generation with mutually exclusive usage buckets, split across a cheap classifier and an expensive drafter, so the spend increase attributes to the right step. |
| **Runbook** | `DEMO_SCRIPT.md` — a six-beat presenter script with the numbers, the questions you will get, and the reset. |
| **Companion** | A live triage console: ask a real question, flip the index between `kb-v1` and `kb-v2`, and watch the same failure happen — emitting a real trace into the same project. |

### Langfuse features on show

Tracing · Sessions · Cost & token tracking · Scores (numeric, categorical,
boolean; trace-, observation- and session-scoped) · User feedback

### Operator knob

**Target traces** (`generation.target_traces`) is the single volume control.
2,000 gives a convincing 28-day picture; 500 is enough for a short session. The
pool is deterministic — the same seed and target reproduce it byte for byte.

## Delivery model

The primary delivery method is **as-is through the depot**, which owns
deployment, seeding, artifacts, and the Companion's lifecycle (delivery-model
decision, 2026-07-29). A standalone-run story exists for development, but the
decision on how kits run individually *outside* the depot is explicitly
deferred — reference it, don't make it.

---

## Development and running outside the depot

Everything below is the kit-dev loop; none of it is needed to deploy or present
the demo through the depot.

### Layout

- `usecase.yaml` — the portal integration manifest (passes `synth-authoring validate`).
- `src/synth/` — the runtime `synth` CLI: `seed` (generate + ingest through the library),
  `verify` (read back through the library), and `companion` (the live surface).
- `src/synth/materialize.py` — deterministic, model-free generation; the single volume
  knob `generation.target_traces` flows through the identity derivation hook in
  `config.py` (this kit's volume *is* a direct trace count).
- `src/synth/kb.py` — the live knowledge base and the broken re-index, used by the
  Companion. Not part of seed generation.
- `src/synth/companion/app.py` — the live triage console on the Companion Adapter.
- `tests/` — the determinism golden gate + manifest validity + the companion suite.
- `Dockerfile` — the reference non-root image.
- `DEMO_SCRIPT.md` — the Presenter Runbook (the `render: markdown` artifact).

### The two halves, and the one law

`materialize.py` is deterministic and **strictly model-free** — no LLM call may emit
observations at seed runtime, and the golden gate proves it by running `seed` in a
subprocess under a deny-LLM egress block. The Companion is the opposite: live, and it
calls a real model. That is allowed precisely because it is not seed runtime.

### Grow it

1. `pip install -e '.[dev]'`
2. `pytest` — the golden gate, manifest checks, and companion suite stay green.
3. `synth-authoring validate usecase.yaml` — the same lint the portal runs at sync.
4. Re-bless a deliberate pool change with `synth-authoring freeze` (never hand-edit the
   golden):

   ```
   synth-authoring freeze golden_seed:seed \
       --golden tests/golden/support_triage_deflection_spool.ndjson \
       --target-traces 24 --search-path tests --search-path src
   ```

5. `synth verify --config config/demo.yaml` against a live seeded project — it asserts the
   regression is actually visible, not just that rows landed.
