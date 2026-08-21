"""Kit config model + loader, and the canonical `target_traces` derivation hook.

The load-and-override *mechanism* lives in the shared library
(`langfuse_synth_core.config.load_config`); this module supplies only the kit's config
*shape* (the `model_factory`) and the derivation hook — pre-wired to the library's trivial
identity derivation (direct count). Replace the identity hook with a bespoke deterministic
mapping when the kit grows a real internal volume model (keep it deterministic so the
golden gate holds).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langfuse_synth_core.config import load_config as _load_config
from langfuse_synth_core.derivation import identity_derivation
from langfuse_synth_core.timegen import parse_as_of_date


@dataclass
class Target:
    """The Langfuse instance a run points at (the library reads `base_url`).

    `host` is the committed default and `LANGFUSE_BASE_URL` overrides it — the retargeting
    rule of CONTRACT.md §"Retargeting". Without it this kit dialled its own loopback on
    every deployment (portal #187); `tests/test_retargeting.py` gates against a regression.
    """

    host: str = "http://localhost:3000"
    project_hint: str = "demo"

    @property
    def base_url(self) -> str:
        # env wins so the same shipped config can target different instances
        return os.environ.get("LANGFUSE_BASE_URL", self.host).rstrip("/")


@dataclass
class Generation:
    seed: int = 42
    target_traces: int = 1000
    # The operator's as-of date: the portal sends `--set generation.as_of_date=YYYY-MM-DD`
    # on every forward generate (portal #72), and the seeded window ends on that day. None
    # means "no tether set" — the CLI path and the no-tether portal path both omit the key —
    # and resolves to the wall clock at seed time (`timegen.resolve_run_date`). A future date
    # is by design (portal #229): never clamp, warn or reject it.
    as_of_date: date | None = None


@dataclass
class Config:
    target: Target
    generation: Generation


def _model_factory(raw: dict) -> Config:
    """Validate a raw config dict into the kit `Config` (the library's `dict -> Config`)."""
    raw = raw or {}
    target = raw.get("target") or {}
    generation = raw.get("generation") or {}
    return Config(
        target=Target(
            host=str(target.get("host", "http://localhost:3000")),
            project_hint=str(target.get("project_hint", "demo")),
        ),
        generation=Generation(
            seed=int(generation.get("seed", 42)),
            target_traces=int(generation.get("target_traces", 1000)),
            as_of_date=parse_as_of_date(generation.get("as_of_date")),
        ),
    )


def load_config(path: str | Path, overrides: list[str] | None = None) -> Config:
    """Read the YAML config, apply `--set dotted.key=value` overrides, and build `Config`."""
    return _load_config(path, _model_factory, overrides)


# The canonical `generation.target_traces` derivation hook (Spec A §4), pre-wired to the
# library's trivial identity derivation (direct count: target_traces -> target_traces).
# Deterministic by contract — identical inputs yield identical internal params — so the
# determinism golden gate holds. Swap for a bespoke mapping in the kit's own migration.
DERIVATION_HOOK = identity_derivation
