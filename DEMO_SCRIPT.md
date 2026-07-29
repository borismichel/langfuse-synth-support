# Presenter Runbook — Support Triage Deflection

> Scaffolded stub. This is the `render: markdown` artifact (declared in `usecase.yaml`)
> the operator reads to walk the demo. Grow it into the real presenter script as the
> story lands — keep the determinism gate green as you go.
>
> **Wiring note:** the portal collects declared artifacts from the container's `/app/out/`
> dir (CONTRACT.md). This committed stub is the source; add a pipeline step (or have `seed`
> render it) that writes the runbook to `/app/out/DEMO_SCRIPT.md` so the portal collects it.

## 1. What this demo shows

_TODO: one paragraph — the story a solutions engineer walks, and the Langfuse feature it
lands (tracing, prompt management, LLM-as-judge, datasets, experiments, scores)._

## 2. Setup

- Deploy the kit. The pipeline runs `synth seed` (generate + ingest) then `synth verify`.
- Volume knob: **Target traces** (`generation.target_traces`) — the single operator control.

## 3. Walk the story

1. _TODO: first beat._
2. _TODO: the turn._
3. _TODO: the close-the-loop payoff._

## 4. Reset

Langfuse ingestion is append-only; teardown is project-level. Delete the Langfuse project
(or create a fresh one) and re-deploy. Re-seeding the same project is safe (deterministic
upsert).
