"""Every Langfuse deep link this kit hands a presenter resolves to a page under v4.

A deep link is a delivery surface: the triage console renders one per turn, an AE clicks it
in front of a customer, and a 404 there is caught by no other gate. v4 reorganised the
Langfuse UI, so the route set this kit may build is pinned here rather than assumed
(portal #212). This kit builds exactly one — the trace detail page — and `/traces/{id}`
survives v4 unchanged; the test exists so that stays true, and so a second link cannot be
added without being checked.
"""
from __future__ import annotations

import pathlib
import re

#: Every project-scoped route this kit may link to, as templates with `{}` for an id.
#: Checked against the v4 app's own routing.
ROUTES = frozenset({"traces", "traces/{}", "sessions", "sessions/{}", "scores"})

SECTIONS = {"traces", "sessions", "scores"}

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

#: The suffix of an f-string project URL: `/project/{...}/<suffix>`. The charset stops at
#: the closing quote and at the backtick a docstring wraps a route in.
_URL = re.compile(r"/project/\{[^}]+\}/([A-Za-z0-9_{}/-]*)")


def _template(suffix: str) -> str:
    suffix = re.sub(r"\{[^}]*\}", "{}", suffix).rstrip("/")
    return "/".join(p if p in SECTIONS else "{}" for p in suffix.split("/") if p)


def test_the_kit_builds_no_link_outside_the_v4_route_set():
    found = [(path, s) for path in sorted(SRC.rglob("*.py"))
             for s in _URL.findall(path.read_text())
             if not re.fullmatch(r"\{[^}]*\}", s)]
    assert found, "no project-scoped URLs found — did the URL shape change?"
    for path, suffix in found:
        assert _template(suffix) in ROUTES, f"{path.relative_to(SRC)}: /project/…/{suffix}"


def test_the_console_links_to_the_trace_detail_page():
    text = (SRC / "synth" / "companion" / "app.py").read_text()
    assert "/traces/{trace_id}" in text
