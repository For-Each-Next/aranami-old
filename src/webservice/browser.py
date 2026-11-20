"""Serve localized data to Vue with a native HTML fallback."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from markupsafe import Markup, escape

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_fallback = ContextVar[str | None]("browser_fallback", default=None)
_PAGE_ASSETS = {
    "about": ("components.js",),
    "consistency": ("components.js",),
    "dataset": ("components.js",),
    "logs": ("components.js",),
    "maintenance": ("components.js",),
    "newsletter": ("components.js", "newsletter.js", "newsletter.css"),
    "quality_analysis": ("quality_analysis.js", "quality_analysis.css"),
    "quality_authorship": ("components.js",),
    "reports": ("components.js",),
}
_BROWSER_ASSETS = (
    "assets/icons/report-icons.svg",
    "assets/images/aranami-wordmark.png",
    *(f"assets/icons/medal-{number}.svg" for number in range(1, 7)),
)
_SCRIPT_ESCAPES = str.maketrans(
    {"<": r"\u003c", ">": r"\u003e", "&": r"\u0026"},
)


@contextmanager
def browser_document(fallback: str | None) -> Iterator[None]:
    """Select a browser document for the current request or fixture."""
    token = _fallback.set(fallback)
    try:
        yield
    finally:
        _fallback.reset(token)


def fallback_url() -> str | None:
    """Return the native HTML URL when the current request uses Vue."""
    return _fallback.get()


def _markup_paths(
    value: object,
    path: tuple[str | int, ...] = (),
) -> Iterator[tuple[str | int, ...]]:
    """Locate the escaped HTML fragments in the view model.

    Yields:
        A sequence of keys and indices for each trusted fragment.
    """
    if isinstance(value, Markup):
        yield path
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _markup_paths(child, (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _markup_paths(child, (*path, index))


def render_document(
    name: str,
    context: dict,
    fallback: str,
    asset_url: Callable[[str], str],
) -> str:
    """Send one complete model in an inert and escaped JSON block.

    Returns:
        A localized HTML shell ready for Vue to mount.
    """
    assets = _PAGE_ASSETS.get(name, ())
    styles = "".join(
        f'<link rel="stylesheet" href="{escape(asset_url(asset))}">'
        for asset in ("styles.css", *assets)
        if asset.endswith(".css")
    )
    scripts = [
        asset_url(asset)
        for asset in (
            "navigation.js",
            *assets,
            *(("live.js",) if context["live"] else ()),
        )
        if asset.endswith(".js")
    ]
    model = json.dumps(
        {
            "schema": 1,
            "page": name,
            "context": {
                **context,
                "assets": {
                    asset: asset_url(asset) for asset in _BROWSER_ASSETS
                },
            },
            "markup": list(_markup_paths(context)),
            "scripts": scripts,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).translate(_SCRIPT_ESCAPES)
    messages = context["t"]
    language = escape(context["language_tag"])
    heading = escape(context["heading"])
    target = escape(fallback)
    return f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#ffffff">
  <meta name="description" content="{escape(messages["page"]["description"])}">
  <link rel="icon" href="{escape(asset_url("assets/images/favicon.png"))}" type="image/png" sizes="32x32">
  <link rel="apple-touch-icon" href="{escape(asset_url("assets/images/aranami-icon.png"))}">
  {styles}
  <title>{heading} · Aranami</title>
  <noscript><meta http-equiv="refresh" content="0;url={target}"></noscript>
  <script type="module" src="{escape(asset_url("app.js"))}"></script>
</head>
<body>
  <div id="aranami-app"><p class="shell"><a href="{target}">{escape(messages["nav"]["html_version"])}</a></p></div>
  <script type="application/json" id="aranami-page">{model}</script>
</body>
</html>
"""  # ruff: ignore[line-too-long]
