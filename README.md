# Support Triage Deflection

A **Demo Depot cartridge** in the making — a runnable-green walking skeleton
scaffolded by `synth-authoring new`. A kit is a cartridge that goes into the
depot: deployed as-is from the portal catalog, it lands the Run-Triad — the
Spool (deterministic backdated data), the Presenter Runbook (`DEMO_SCRIPT.md`),
and optionally a Companion (the live surface). This scaffold's determinism
plumbing (backdated ingestion through the shared library, spool determinism,
non-root uid 10001) is proven before any story logic lands.

The portal serves this file as the kit's catalog **Overview** doc. Keep it
depot-first: everything above the marked section at the bottom is what a
presenter or operator reads — the story, what deploying lands, how the
Companion plays. Development content stays below the mark.

## What this demo is

*Replace this with the story: the business, the tension, the arc a presenter
walks — and what the Run-Triad contains once the story lands.*

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
- `src/synth/` — the runtime `synth` CLI: `seed` (generate + ingest through the library)
  and `verify` (read back through the library).
- `src/synth/materialize.py` — deterministic, model-free generation; the single volume
  knob `generation.target_traces` flows through the identity derivation hook in `config.py`.
- `tests/` — the determinism golden gate (green from the first commit) + manifest validity.
- `Dockerfile` — the reference non-root image.
- `DEMO_SCRIPT.md` — the Presenter Runbook stub (the `render: markdown` artifact).

### Grow it

1. `pip install -e '.[dev]'`
2. `pytest` — the golden gate + manifest checks stay green.
3. Replace the identity derivation hook and grow `materialize.py` into the real story,
   keeping the gate green. Re-bless a deliberate pool change with `synth-authoring freeze`
   (never hand-edit the golden).
