"""Determinism golden gate — same (seed, target_traces, params) => byte-identical Spool.

A fresh full-payload materialization is compared byte-for-byte against the blessed golden,
run offline in a subprocess under PYTHONHASHSEED=0 and the deny-LLM egress block. This
simultaneously proves the seed is deterministic AND model-free-at-seed-runtime. `synth new`
blessed the initial golden, so this is green from the first commit.

The oracle is pinned at a small `GOLDEN_TARGET_TRACES` floor: determinism is
scale-independent, so a tiny committed golden proves the law while staying reviewable.
Re-bless a deliberate pool change (never a hand-edit) with:

    synth-authoring freeze golden_seed:seed \\
        --golden tests/golden/support_triage_deflection_spool.ndjson \\
        --target-traces 24 --search-path tests --search-path src
"""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("jsonschema") is None,
    reason="golden gate ships in langfuse-synth-core[authoring]; install the [dev] extra to run it",
)

GOLDEN_TARGET_TRACES = 24
GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "support_triage_deflection_spool.ndjson"
TESTS_DIR = str(Path(__file__).resolve().parent)
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")


def _spec():
    from langfuse_synth_core.authoring.golden import GoldenSpec

    return GoldenSpec(
        seed_ref="golden_seed:seed",
        target_traces=GOLDEN_TARGET_TRACES,
        golden_path=GOLDEN_PATH,
        params={},
        search_paths=(TESTS_DIR, SRC_DIR),
    )


def test_full_payload_golden_is_byte_identical():
    """A fresh full-Spool materialization is byte-identical to the blessed oracle."""
    from langfuse_synth_core.authoring.golden import assert_golden

    assert_golden(_spec())


def test_golden_is_full_payload_not_ids_and_summary():
    """The blessed oracle is the whole Spool — traces, generations, and scores."""
    blob = GOLDEN_PATH.read_bytes()
    assert b'"type":"trace-create"' in blob
    assert b'"type":"generation-create"' in blob
    assert b'"type":"score-create"' in blob
