"""The retargeting gate — this kit's config must honor `LANGFUSE_BASE_URL`.

The portal ships ONE config (`config/demo.yaml`) and points it at whatever Langfuse a
deployment targets, by injecting `LANGFUSE_BASE_URL` into the container. A kit that reads only
its config file therefore dials its own committed `host` — usually loopback — wherever it is
deployed, and fails at `seed` with a connection error against localhost (portal #187).

Nothing else in this suite can see that: `test_validate.py` lints the manifest, and the
determinism golden seeds from a fixed config file. This gate is the one place the env-configured
portal path is exercised at authoring time, and it is offline — a config-resolution law, not a
connectivity check — so it costs nothing to keep green.

Keep this test. If `Target.base_url` stops letting the env win, this kit stops being deployable.
"""
import importlib.util
from pathlib import Path

import pytest

# The gate imports `langfuse_synth_core.authoring`, which requires the [authoring] extra (it is
# pulled in by this kit's [dev] extra, so CI always runs the gate — `ci.yml` installs
# `.[dev]`). Skipping on a bare runtime install matches the sibling gates in this directory.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("jsonschema") is None,
    reason="the retargeting gate ships in langfuse-synth-core[authoring]; install [dev] to run it",
)

CONFIG = Path(__file__).resolve().parent.parent / "config" / "demo.yaml"


def test_config_is_retargetable_by_the_portal():
    """`LANGFUSE_BASE_URL` wins over the committed `target.host`, and with the var absent the
    committed value is still the default (so offline runs and the golden gate keep working)."""
    from langfuse_synth_core.authoring.retarget import assert_retargetable

    from synth.config import load_config

    assert_retargetable(load_config, CONFIG)
