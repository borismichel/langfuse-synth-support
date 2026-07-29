---
name: authoring-a-demo-kit
description: >-
  Author a new Demo Depot synth kit with langfuse-synth-core — scaffold a runnable-green
  walking skeleton, model its trace tree, wire the target_traces derivation, grow the
  Presenter Runbook, and keep the determinism + validate gates green. Use when building a
  new demo package / synth kit, adding a use case to Demo Depot, or working in a repo that
  pins langfuse-synth-core. Enforces the model-free-seed law and delegates Langfuse craft
  (which observation type, which evaluator) to the `langfuse` skill.
---

# Authoring a Demo Kit

You are building a **Demo Depot synth kit**: a small repo whose `usecase.yaml` is the only
surface the portal reads, and whose `synth seed` deterministically ingests backdated
Langfuse data that tells a scenario story. This skill is the orchestrator — it walks you
from an empty directory to a kit that stays green through every gate.

Two jobs are split cleanly, and this skill only owns the first:

- **Contract compliance → mechanical, red/green.** The validator and the determinism gate
  tell you yes/no. This skill drives them.
- **Langfuse craft → judgment.** *Which* observation type models this step, *which*
  evaluator type scores it — the validator cannot check that. **Delegate it to the
  `langfuse` skill.** (See
  [references/langfuse-craft.md](references/langfuse-craft.md).) Do not reason about
  Langfuse semantics from memory here; that skill fetches current docs.

There is exactly **one law** you must never break: **seed runtime is model-free.** No LLM
call emits observations at seed time. It is not a style rule — a runtime egress block
*proves* it at every gate run. The sanctioned escape hatch (a one-off LLM call at
*authoring* time, frozen as a static fixture) is a first-class pattern taught below and in
[references/model-free-seed.md](references/model-free-seed.md). Read that reference before
you are ever tempted to "enrich" a story with a live model call.

## Prerequisites

```bash
pip install 'langfuse-synth-core[authoring]'      # brings the synth-authoring CLI + gates
```

This skill ships *inside* that extra, versioned with the library — so the CLI you run and
the skill you follow can never drift. To make sibling skills discoverable to your agent:

```bash
synth-authoring skills                # list the shipped kit-dev skills
synth-authoring skills --install      # copy them into .claude/skills/
```

Keep the `langfuse` skill available too — you will
hand off to it in Phase 2 and Phase 5.

## The workflow

Do these in order. The kit is **green from Phase 1** and must stay green — after every
change, run the gates (Phase 5) before moving on. Never hand-edit a golden snapshot; grow
the story and re-bless.

### Phase 1 — Scaffold (`synth-authoring new`)

```bash
synth-authoring new my-kit --dir ../kits          # kit lands at ../kits/my-kit
synth-authoring new my-kit --companion            # also emit the companion stub (Spec G)
synth-authoring new my-kit --core-ref v1.4.0      # lib git tag the kit pins to
```

This emits a **runnable-green walking skeleton**, not a blank template: the plumbing
(backdated ingestion through the library, spool determinism, non-root uid 10001) is proven
before any story logic lands, and the initial determinism golden is already blessed. The
file floor you now own:

| File | What it is | You edit it in |
| --- | --- | --- |
| `usecase.yaml` | The portal manifest (schema-valid, canonical `generation.target_traces` knob injected). The *only* portal surface. | Phase 4 (artifacts), as the story lands |
| `src/synth/materialize.py` | **Deterministic, model-free generation** — the trace tree. | **Phase 2** |
| `src/synth/config.py` | Config model + the `DERIVATION_HOOK` (identity by default). | **Phase 3** |
| `src/synth/seed.py` / `verify.py` / `cli.py` | `seed`/`verify` wired through the library. | Rarely — grow verbs here + in `usecase.yaml` together |
| `DEMO_SCRIPT.md` | The `render: markdown` Presenter Runbook stub. | **Phase 4** |
| `tests/` | The determinism golden gate + manifest-validity test (green now). | Never by hand — re-bless via `freeze` |
| `Dockerfile` | The reference non-root image. | Only for real runtime deps |

Then confirm the floor is real before you touch anything:

```bash
cd ../kits/my-kit && pip install -e '.[dev]' && pytest      # green from the first commit
```

### Phase 2 — Model the trace tree

`src/synth/materialize.py::build_events` is where generation lives, and the **only** place
it lives. It builds Langfuse ingestion events through the library's event builders and its
deterministic RNG — nothing else. The skeleton emits, per trace: one `trace_event`, one
`generation_event`, one `score_event`. Grow that into your scenario's tree.

The library gives you the write primitives (import from `langfuse_synth_core.seed.events`):

- `trace_event` — the root of one trace.
- `span_event` — a non-LLM unit of work (a retrieval, a tool call, a routing step).
- `generation_event` — an **LLM** step (carries model, token usage, cost).
- `event_event` — a point-in-time marker.
- `observation_event` — the generic escape hatch when none of the above fits.
- `score_event` — an evaluation/score attached to a trace or observation.

**Determinism is the constraint that shapes this code.** Every id, timestamp, and value
must derive from the seeded RNG (`langfuse_synth_core.rng.Rng`), never from a wall clock,
`random` without a seed, `uuid4`, set iteration order, or a network call:

- Draw all randomness from `rng.sub("namespace", i)` substreams — stable, independent, and
  reproducible. Use `r.trace_id(i)` / `r.obs_id(i)` / `r.score_id(i)` for W3C-format ids.
- Backdate from a **fixed anchor** (`RUN_DATE` in the template), never `datetime.now()`.
  Use `langfuse_synth_core.timegen.sample_timestamps` for a realistic backdated spread.
- The single operator volume knob flows in as `target_traces` and must pass through
  `DERIVATION_HOOK` (Phase 3) — do not read a bespoke count.

**Hand off the semantic choices to the `langfuse` skill.** *Which* observation type a step
should be, whether a step is a generation vs. a span, what score names/data-types make the
scenario legible in the Langfuse UI, and which evaluator type fits — that is Langfuse craft,
not contract. Ask the `langfuse` skill; it fetches
current docs rather than guessing. This skill only guarantees the result stays deterministic
and model-free. See [references/langfuse-craft.md](references/langfuse-craft.md) for the
exact boundary.

After every change here, run Phase 5. If the golden gate now fails and the change was
**intentional**, re-bless (Phase 5); if it was accidental, you perturbed determinism — fix
it (usually an unseeded random source crept in).

### Phase 3 — Wire the `target_traces` derivation

Every volume-adjustable kit exposes the **same** operator knob: `generation.target_traces`
(already injected into `usecase.yaml`). A kit-side **deterministic** hook maps that one knob
to your kit's internals, so the portal stays zero-code (it passes
`--set generation.target_traces=N` verbatim) and determinism holds.

In `src/synth/config.py` the hook is pre-wired to the trivial identity derivation:

```python
from langfuse_synth_core.derivation import identity_derivation
DERIVATION_HOOK = identity_derivation      # target_traces -> {"target_traces": target_traces}
```

If your kit's volume *is* a direct trace count, leave it. If `target_traces` should drive
something internal (a scale multiplier, a per-cohort split, a number of experiment runs),
replace it with your own hook:

```python
def DERIVATION_HOOK(target_traces: int, declared) -> dict:
    # DETERMINISTIC: identical (target_traces, declared) -> identical output, always.
    # Fixed golden assets (a canned suite, seeded experiments) stay UNSCALED.
    return {"target_traces": target_traces, "scale": max(1, target_traces // 100)}
```

The contract the hook must uphold: `seed + target_traces (+ declared params) →
byte-identical Spool`, with fixed golden assets left unscaled. Keep it pure and
deterministic or the golden gate will (correctly) go red.

### Phase 4 — Grow the Presenter Runbook

`DEMO_SCRIPT.md` is the `render: markdown` artifact declared in `usecase.yaml` — the script
a solutions engineer reads to walk the demo. At least one `render: markdown` artifact is
mandatory; the scaffold ships this one. Grow the stub into the real walkthrough: what the
demo shows, the setup, the story beats, the reset.

**Wiring note (deploy-time, not a gate).** Per `CONTRACT.md` ("Filesystem conventions"),
the portal collects declared artifacts from the container's `/app/out/` directory after the
producing step exits — so the committed `DEMO_SCRIPT.md` is the *source*, and for the portal
to actually collect it a pipeline step (or `seed`) must write the runbook to
`/app/out/DEMO_SCRIPT.md`. This doesn't affect the local gates (the manifest is valid with
`path: DEMO_SCRIPT.md` as-is, exactly as the scaffold ships it) — it's what makes the runbook
show up in a real deploy, matching the wiring note in the scaffolded `DEMO_SCRIPT.md` stub.
If you add pipeline steps, keep `usecase.yaml` and `src/synth/cli.py` in sync (a reserved-verb
step id must run `synth <that verb>` — see `CONTRACT.md`).

### Phase 5 — Run the gates

Three offline/dev gates, cheapest first. Run them after every phase; all must be green
before the kit is done.

```bash
# 1. Static Contract lint — same code the portal runs at sync (offline, instant).
synth-authoring validate usecase.yaml

# 2. Determinism golden gate + manifest validity (offline, under the deny-LLM egress block).
pytest

# 3. Read-back suite against a LIVE seeded env — asserts the scenario truth landed.
synth verify --config config/demo.yaml       # needs a seeded Langfuse project
```

**Re-blessing the golden — the only correct way to change the pool.** When you *deliberately*
change generation (Phase 2/3) or refresh a frozen fixture, the golden gate goes red because
the Spool bytes changed. Do **not** edit the snapshot. Re-bless it in one intentional step:

```bash
synth-authoring freeze golden_seed:seed \
    --golden tests/golden/my_kit_spool.ndjson \
    --target-traces 24 --search-path tests --search-path src
```

`freeze` re-materializes the Spool under the same deny-LLM egress block and writes it as the
new oracle — so an accidental drift still fails, but an intended change is a deliberate
re-bless, reviewable in the diff.

## The one law: seed runtime is model-free

**No LLM call may emit observations at seed runtime.** This is enforced, not requested: the
determinism golden gate runs `seed` in a subprocess under a **deny-LLM egress block** (a
socket-level guard plus proxy/base-url env pointed at an unroutable sink). A planted LLM
call — anywhere under `seed`, in *your* generation code, even via a dynamic import — trips
it and the gate fails with `EgressBlockedError`. The skill tells you the rule; the gate
proves you followed it.

Why it matters here specifically: the library's write machinery is model-free by
construction, but **your** `materialize.py` is agent-authored and is exactly the code
tempted to call a model to "enrich" a story. The gate guards *your* code.

### The sanctioned escape hatch (use this instead)

A legitimate one-off LLM call belongs at **authoring time**, with its output **frozen into
the recipe as a static fixture** that seed replays deterministically:

1. At authoring time (in a script or notebook, *not* in `materialize.py`), call the model
   once and capture its output.
2. Commit that output as a static fixture (a JSON/text file, or an in-repo constant).
3. Have `materialize.py` read the frozen fixture — never the model — at seed time.
4. `synth-authoring freeze` re-blesses the golden so the new fixture is the oracle.

Seed runtime then replays frozen data; the rule stays a clean binary (no LLM at seed
runtime, once or per-unit). Full pattern in
[references/model-free-seed.md](references/model-free-seed.md).

## What "done" looks like

- `synth-authoring validate usecase.yaml` — valid.
- `pytest` — green (determinism golden gate + manifest validity), under the egress block.
- `synth verify` — the scenario truth reads back from a live seeded env.
- The trace tree and runbook tell the real story; Langfuse semantic choices were made with
  the `langfuse` skill, not from memory.
- No LLM call at seed runtime; any author-time model use is frozen as a fixture and blessed.

## References

- [references/model-free-seed.md](references/model-free-seed.md) — the model-free law, the
  egress gate, and the author-time-LLM-frozen-fixture escape hatch, in depth.
- [references/langfuse-craft.md](references/langfuse-craft.md) — the exact split between
  contract (this skill) and Langfuse craft (the `langfuse` skill).
- `CONTRACT.md` (in the library repo) — reserved-verb semantics, filesystem conventions,
  the canonical volume knob, LLM-provider rules.
- `docs/SEAM.md` — the library/kit hand-off rule (what the lib owns vs. what the kit owns).
