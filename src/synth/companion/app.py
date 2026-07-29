"""Companion surface — a runnable-green live app on the Companion Adapter (Spec G · G3).

`synth-authoring new --companion` emits this as a **working** skeleton, not a stub: it boots
through the shared `CompanionAdapter`, binds `0.0.0.0:<port>`, answers its health path, and
renders a placeholder page via the runtime theme helpers. Grow it into the kit's live scene —
add routes and forms to `create_app` — while the Adapter keeps owning invocation, bind,
health, shutdown, secret intake, and the ready Langfuse + LLM clients:

  * the Surface receives the adapter and asks it for ready clients (`adapter.langfuse()`,
    `adapter.ingestor()`, `adapter.read_json(...)`, `adapter.llm()`); it never reads a raw
    key, sentinel, or env var — secret intake is the Adapter's job (D4);
  * `main` is wired to the kit's `synth companion` verb (src/synth/cli.py) and declared under
    `live_components` in usecase.yaml; it parses the fixed `--config/--host/--port` invocation
    with the Adapter's `parse_invocation` helper (never a pipeline `--set`).
"""
from __future__ import annotations

from typing import Any

from langfuse_synth_core.companion import CompanionAdapter, parse_invocation
from langfuse_synth_core.live import paths, theme

# Kept in step with the `live_components` entry in usecase.yaml (the scaffold pins them
# together). HEALTH_PATH is the Adapter's readiness route and MUST differ from `/` (the
# surface's own page), since the Adapter mounts readiness at the health path.
HEALTH_PATH = "/healthz"
REQUIRES_SECRETS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LLM_API_KEY")


def _placeholder_page() -> str:
    """The starter page, rendered through the shared Langfuse-styled shell (`live.theme`)."""
    body = (
        "<p class='eyebrow'>Companion surface</p>"
        "<h1>Your <span class='mark'>live</span> scene starts here.</h1>"
        "<p class='sub'>Scaffolded by <code>synth-authoring new --companion</code>. This "
        "placeholder is served by the Companion Adapter — replace it with the demo's "
        "interactive surface. Your routes get ready Langfuse + LLM clients from the adapter; "
        "you never handle a raw secret.</p>"
        f"<a class='back' href='{paths.local(HEALTH_PATH)}'>readiness &rarr;</a>"
    )
    return theme.page(body, title="Support Triage Deflection · companion")


def create_app(adapter: CompanionAdapter) -> Any:
    """Build the live Surface on ``adapter`` (its ready clients) and return a FastAPI app.

    Serves the placeholder page at ``/``; the Adapter mounts the health route and owns
    bind/serve. Grow the scene here — read the seeded pool with ``adapter.read_json(...)``,
    emit live traces with ``adapter.ingestor()``, call the model with ``adapter.llm()``.
    """
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def _root() -> str:
        return _placeholder_page()

    return app


def main(argv: list[str] | None = None) -> int:
    """`synth companion --config {config} --host 0.0.0.0 --port <p>` — boot the Surface.

    Parses the fixed live invocation with the Adapter's `parse_invocation` (rejecting any
    stray pipeline `--set`), builds the Adapter from the kit config + manifest values, and
    inherits invocation/bind/health/shutdown/secret-intake by handing it `create_app`.
    """
    from synth.config import load_config

    inv = parse_invocation(argv)
    cfg = load_config(inv.config)
    adapter = CompanionAdapter(
        cfg, requires_secrets=REQUIRES_SECRETS, health_path=HEALTH_PATH
    )
    adapter.run(create_app, host=inv.host, port=inv.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
