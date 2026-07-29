"""Kit config model + loader, and the canonical `target_traces` derivation hook.

The load-and-override *mechanism* lives in the shared library
(`langfuse_synth_core.config.load_config`); this module supplies only the kit's config
*shape* (the `model_factory`) and the derivation hook — pre-wired to the library's trivial
identity derivation (direct count). Replace the identity hook with a bespoke deterministic
mapping when the kit grows a real internal volume model (keep it deterministic so the
golden gate holds).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langfuse_synth_core.config import load_config as _load_config
from langfuse_synth_core.derivation import identity_derivation


@dataclass
class Target:
    """The Langfuse instance a run points at (the library reads `base_url`)."""

    base_url: str = "http://localhost:3000"
    project_hint: str = "demo"


@dataclass
class Generation:
    seed: int = 42
    target_traces: int = 1000


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
            base_url=str(target.get("base_url", "http://localhost:3000")),
            project_hint=str(target.get("project_hint", "demo")),
        ),
        generation=Generation(
            seed=int(generation.get("seed", 42)),
            target_traces=int(generation.get("target_traces", 1000)),
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
