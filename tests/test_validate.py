"""The scaffolded `usecase.yaml` passes `synth-authoring validate` with no edits.

Runs the same importable validator the portal uses at sync time, so "green here" ==
"passes portal sync" by construction. Skips on a bare install without the [authoring]
extra (which ships the validator).
"""
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("jsonschema") is None,
    reason="validate ships in langfuse-synth-core[authoring]; install the [dev] extra to run it",
)

MANIFEST = Path(__file__).resolve().parent.parent / "usecase.yaml"


def test_manifest_is_valid():
    from langfuse_synth_core.authoring.validate import validate_path

    errors = validate_path(MANIFEST)
    assert errors == [], "usecase.yaml is invalid:\n" + "\n".join(errors)


def test_manifest_exposes_the_canonical_volume_knob():
    import yaml

    doc = yaml.safe_load(MANIFEST.read_text())
    props = doc["config_schema"]["properties"]
    assert "generation.target_traces" in props
    assert props["generation.target_traces"]["type"] == "integer"


def test_support_declares_fixed_history_and_authored_rehearsal_without_a_plan():
    import yaml
    from synth.config import load_config

    doc = yaml.safe_load(MANIFEST.read_text())
    setup = doc['setup']
    assert setup['schedule'] == {
        'timezone': 'UTC', 'end': 'inclusive', 'history': {'fixed_days': 28},
    }
    assert setup['presets']['quick_rehearsal']['values'] == {'generation.target_traces': 200}
    cfg = load_config('config/demo.yaml')
    assert doc['config_schema']['properties']['generation.target_traces']['default'] == cfg.generation.target_traces == 1000
    assert doc['config_schema']['properties']['generation.seed']['default'] == cfg.generation.seed == 42
    assert [step['id'] for step in doc['pipeline']] == ['seed', 'verify']
