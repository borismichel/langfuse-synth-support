"""The operator's as-of date reaches the seed (portal #229).

The portal has sent `--set generation.as_of_date=YYYY-MM-DD` on every forward generate
since #72; until #229 this kit froze `RUN_DATE = 2026-07-29` in `src/` instead, which is
why a fresh deployment looked empty under Langfuse's default time filter. These pin the
knob end to end through the REAL operator path — the `--set` override, the config model,
`run_seed`'s anchor — and pin that no date constant is left in shipped code.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from synth.config import load_config
from synth.seed import run_seed

REPO = Path(__file__).resolve().parent.parent
CONFIG = str(REPO / "config" / "demo.yaml")
SMALL = "generation.target_traces=120"


def _seed(tmp_path: Path, *overrides: str) -> list[str]:
    """Run the runtime seed in dry-run; return every score timestamp the Spool carries."""
    cfg = load_config(CONFIG, overrides=[SMALL, *overrides])
    spool = run_seed(cfg, dry_run=True, do_import=False, spool_path=tmp_path / "events.ndjson",
                     log=lambda _m: None)
    return [json.loads(line)["timestamp"] for line in spool.read_text().splitlines()
            if '"score-create"' in line]


def _window_end(stamps: list[str]) -> date:
    return date.fromisoformat(max(stamps)[:10])


def _assert_ends_on(stamps: list[str], as_of: date) -> None:
    # `sample_timestamps` draws whole hours up to the anchor day's midnight, so the newest
    # sample lands late on the eve of the as-of date (or on it) — never after it.
    assert as_of - timedelta(days=1) <= _window_end(stamps) <= as_of, (max(stamps), as_of)


def test_the_override_lands_on_the_config_as_a_date():
    cfg = load_config(CONFIG, overrides=["generation.as_of_date=2026-09-04"])
    assert cfg.generation.as_of_date == date(2026, 9, 4)


def test_absent_means_no_tether():
    assert load_config(CONFIG).generation.as_of_date is None


def test_seed_anchors_the_window_on_the_as_of_date(tmp_path):
    _assert_ends_on(_seed(tmp_path, "generation.as_of_date=2026-09-04"), date(2026, 9, 4))


def test_a_future_as_of_date_is_honoured_not_clamped(tmp_path):
    """By design: an AE tethers next week's demo to the meeting. The window simply ends on
    that date — no error, no warning, no clamp to today."""
    fortnight_out = datetime.now(timezone.utc).date() + timedelta(days=14)
    _assert_ends_on(_seed(tmp_path, f"generation.as_of_date={fortnight_out.isoformat()}"),
                    fortnight_out)


def test_no_as_of_date_seeds_up_to_now(tmp_path):
    """The symptom that started this: with no tether the window ends now, so a fresh
    deployment is visible under Langfuse's default time filter."""
    stamps = _seed(tmp_path)
    _assert_ends_on(stamps, datetime.now(timezone.utc).date())


def test_same_three_inputs_give_identical_bytes_regardless_of_the_clock(tmp_path):
    """The determinism law, third leg included: two runs with the same seed, target_traces
    and as-of date produce identical Spool bytes — the wall clock is not an input."""
    _seed(tmp_path / "a", "generation.as_of_date=2026-09-04")
    _seed(tmp_path / "b", "generation.as_of_date=2026-09-04")
    assert (tmp_path / "a" / "events.ndjson").read_bytes() == \
        (tmp_path / "b" / "events.ndjson").read_bytes()


def test_no_date_constant_ships_in_src():
    """Determinism belongs to the gate: the only pinned date is `tests/golden_seed.py`'s
    `AS_OF_DATE`; nothing under `src/` may carry one."""
    adapter = (REPO / "tests" / "golden_seed.py").read_text()
    assert re.search(r'AS_OF_DATE = "\d{4}-\d{2}-\d{2}"', adapter)
    for path in (REPO / "src").rglob("*.py"):
        body = "\n".join(line for line in path.read_text().splitlines()
                         if not line.lstrip().startswith("#"))
        assert not re.search(r"datetime\(\s*20\d\d\s*,", body), path
        assert "RUN_DATE" not in body and "REINDEX_AT" not in body, path
