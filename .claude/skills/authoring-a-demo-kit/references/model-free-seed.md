# The model-free-seed law and its escape hatch

The determinism law of a Demo Depot kit is:

> `seed + target_traces + declared params → byte-identical Spool`, with **no LLM emitting
> observations at seed runtime.**

This reference is the depth behind the one rule in the orchestrator skill. Read it before
you ever consider a live model call inside generation code.

## Why "no LLM at seed runtime" is a hard binary

A demo kit's value is that it reproduces a *vendor-approved* dataset exactly. An LLM call at
seed time breaks that two ways:

1. **Non-determinism.** Model output varies run to run (sampling, model updates, provider
   drift). The byte-identical Spool law is instantly false, and the golden gate can no
   longer catch a regression, because "different bytes" is now expected.
2. **Egress at deploy time.** Deployed kits seed under a default-deny egress posture. A
   model call that "worked on my machine" fails — or worse, silently degrades — in
   production.

The rule is binary: **no LLM at seed runtime, whether once or per-unit.** There is no
"just one small call" exception at seed time. The legitimate need — a one-off model call to
generate content — is real, and it has a sanctioned home: **authoring time** (below).

## How the gate proves it (not a static scan)

A static provider-scan ("grep for `anthropic`") is theatre — a dynamic import evades it. The
binding enforcement is a **real runtime egress block**. Every determinism gate run
(`pytest`, `synth-authoring freeze`, `synth-authoring new`'s initial bless) does this:

- `seed` runs in a **subprocess** under `PYTHONHASHSEED=0` (so set/dict ordering can't
  perturb bytes) and a **deny-LLM egress block**:
  - a **socket-level guard** monkeypatches `getaddrinfo` / `create_connection` /
    `socket.connect[_ex]` so any **non-loopback** target raises `EgressBlockedError`
    *before* DNS or a connection happens;
  - **proxy / base-url env** (`HTTPS_PROXY`, `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, …) is
    pointed at an unroutable sink (RFC 5737 `192.0.2.1`), so an SDK that honours those is
    steered somewhere the guard then denies.
- Loopback is allowed (local IPC, a temp server), because the offline seed makes no
  outbound calls at all.

So a planted LLM call **anywhere under `seed`** — including in *your* `materialize.py`, even
behind a dynamic import — trips the block and the gate fails:

```
langfuse_synth_core.authoring.egress.EgressBlockedError: seed attempted LLM/network egress
under the deny-LLM egress block — seed runtime must be model-free (move any one-off LLM call
to authoring time and freeze its output as a static fixture).
```

This is why the gate guards **your** code, not just the library's. The library's write
machinery is model-free by construction; your agent-authored generation code is exactly what
is tempted to "enrich" a story with a live call. The gate is what makes the skill's
instruction binding.

**Trust boundary (by design).** The guard covers the TCP/DNS entry points every real LLM SDK
uses. It does not chase UDP, a shelled-out `curl`, or code reaching the raw C `_socket`
directly — those still *fail* the gate (the sink env errors them) but as a generic failure,
not a typed `EgressBlockedError`. The goal is a binding, deterministic block on the
model-call path, not a sandbox; defeating it takes deliberate effort your generation code
has no reason to make.

## The sanctioned escape hatch: author-time LLM → frozen fixture

When you genuinely need model-generated content (a realistic support transcript, a plausible
agent answer, a corpus of varied prompts), do it **once, at authoring time**, and freeze the
output. Seed then replays the frozen data deterministically.

The pattern, step by step:

1. **Generate at authoring time — outside generation code.** In a one-off script or notebook
   (never in `src/synth/materialize.py`), call the model and capture its output. This runs
   on your dev box, not at seed time, so no gate applies to it.

   ```python
   # tools/generate_fixture.py — runs ONCE, by hand, at authoring time. Never imported by seed.
   import json, anthropic
   client = anthropic.Anthropic()
   transcripts = [call_model(client, topic) for topic in TOPICS]
   json.dump(transcripts, open("src/synth/fixtures/transcripts.json", "w"), indent=2)
   ```

2. **Commit the output as a static fixture.** A JSON/text file in the kit (e.g.
   `src/synth/fixtures/transcripts.json`) or an in-repo constant. This is now vendor-approved
   content, reviewed in the diff like any other asset.

3. **Read the fixture — never the model — at seed time.** `materialize.py` loads the frozen
   file and draws from it deterministically with the seeded RNG:

   ```python
   from importlib import resources
   import json

   _TRANSCRIPTS = json.loads(
       resources.files("synth.fixtures").joinpath("transcripts.json").read_text()
   )

   def build_events(target_traces, params):
       ...
       transcript = r.choice(_TRANSCRIPTS)   # frozen data, chosen deterministically
       ...
   ```

4. **Bless the golden.** Because the pool changed on purpose, re-bless the oracle in one
   intentional step (never hand-edit the snapshot):

   ```bash
   synth-authoring freeze golden_seed:seed \
       --golden tests/golden/<slug>_spool.ndjson \
       --target-traces 24 --search-path tests --search-path src
   ```

5. **Refreshing later** repeats steps 1–4: regenerate the fixture at authoring time, commit
   it, re-`freeze`. The refresh is a deliberate, reviewable event — not a silent per-run
   drift.

The net effect: the rule stays a clean binary (no LLM at seed runtime), you still get
model-generated richness, and the determinism gate stays meaningful because seed replays
frozen bytes.

## Quick checklist

- [ ] `materialize.py` imports no LLM SDK and makes no network call.
- [ ] Every random value comes from the seeded `Rng` (no `uuid4`, no unseeded `random`, no
      `datetime.now()`).
- [ ] Any model-generated content is a committed fixture, generated by an author-time script
      that seed never imports.
- [ ] `pytest` is green under the egress block; a deliberate pool change was re-blessed with
      `synth-authoring freeze`, not hand-edited.
