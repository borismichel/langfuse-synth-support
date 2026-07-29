# The split: Contract (this skill) vs. Langfuse craft (the `langfuse` skill)

Authoring a kit has two kinds of question, and confusing them is how kits go wrong. This
reference draws the line so you know, at every decision, which skill answers.

## The clean split

| | **Contract** | **Langfuse craft** |
| --- | --- | --- |
| Owner | **This skill** + the validator | The **`langfuse` skill** |
| Nature | Mechanical, red/green | Judgment, docs-driven |
| Checked by | `synth-authoring validate`, the determinism golden gate | Nothing automatic — it's modelling taste |
| Examples | Is `seed`+`verify` present? Is the manifest schema-valid? Is there a `render: markdown` artifact? Is the pool byte-identical and model-free? | *Which* observation type is this step? *Which* evaluator/score fits? What trace structure reads well in the Langfuse UI? |

If a question has a yes/no answer a tool can compute, it's Contract — stay here. If it needs
knowledge of how Langfuse models the world, it's craft — **ask the `langfuse` skill, which
fetches current docs rather than reasoning from memory** (Langfuse changes often).

## Hand off to the `langfuse` skill for these

- **Observation type.** Is a step a `generation` (an LLM call — carries model, tokens, cost),
  a `span` (a unit of work — retrieval, tool call, routing), an `event` (a point-in-time
  marker), or the generic `observation`? The library gives you a builder for each
  (`generation_event`, `span_event`, `event_event`, `observation_event` from
  `langfuse_synth_core.seed.events`); *which* one models your scenario truthfully is craft.
- **Evaluator / score design.** Which evaluator type (LLM-as-judge, heuristic, human
  annotation), what score `name`s, what `data_type` (NUMERIC / CATEGORICAL / BOOLEAN), and
  what value ranges make the scenario legible and the demo's point land. The
  `langfuse` skill's judge-calibration and error-analysis references cover this.
- **Trace tree shape.** How deep to nest, how to name observations, how to attach metadata
  so a solutions engineer walking the Langfuse UI sees the story.
- **Anything you'd otherwise guess about Langfuse from memory.** Don't. That skill exists to
  fetch the current answer.

## Keep here (Contract — don't outsource)

- **Determinism.** Whatever the `langfuse` skill advises, the result must be built from the
  seeded `Rng` and stay byte-identical. See [model-free-seed.md](model-free-seed.md).
- **Model-free at seed runtime.** Craft advice never justifies a live model call in
  generation code. If the `langfuse` skill's guidance implies generated content, use the
  author-time-fixture escape hatch.
- **The manifest contract.** `seed`+`verify` present, reserved-verb semantics, the canonical
  `generation.target_traces` knob, ≥1 `render: markdown` artifact — the validator owns these.
- **The library seam.** The kit composes the trace tree from library primitives; it does not
  reimplement event emission, backdating, ingest, or the read client. See `docs/SEAM.md`.

## Why delegate instead of duplicate

If this skill re-taught Langfuse's observation model, it would drift from Langfuse's actual
docs the moment either changed — and it would duplicate a skill that already does the job
well and stays current. The Authoring SDK's job is to make **contract compliance**
mechanical; **Langfuse craft** is judgment the validator can't check, so it belongs to the
skill built for it. One version of each, no overlap.
