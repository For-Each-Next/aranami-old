"""Share read-only HTTP responses across runtime endpoints."""

import gzip
from http import HTTPStatus

_COMPRESS_MIN_BYTES = 1024


def read_only_headers(
    status: int,
    *,
    websocket_origin: str | None = None,
) -> dict[str, str]:
    """Return the security and cache policy for saved public responses.

    Args:
        status: HTTP response code, including method rejections.
        websocket_origin: Trusted origin allowed for status pushes.

    Returns:
        Transport-independent headers shared by both runtime servers.
    """
    connect_sources = "'self'"
    if websocket_origin:
        connect_sources += f" {websocket_origin}"
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'self'; script-src 'self'; "
            f"img-src 'self'; connect-src {connect_sources}; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        ),
    }
    if status == HTTPStatus.METHOD_NOT_ALLOWED:
        headers["Allow"] = "GET, HEAD"
    return headers


def encoded_response(
    content: bytes,
    encodings: str,
) -> tuple[bytes, dict[str, str]]:
    """Compress complete response bytes when negotiated and worthwhile.

    Args:
        content: Complete body; streamed downloads bypass this helper.
        encodings: The request's Accept-Encoding field.

    Returns:
        Encoded bytes and the corresponding negotiation headers.
    """
    headers = {"Vary": "Accept-Encoding"}
    if len(content) >= _COMPRESS_MIN_BYTES and accepts_gzip(encodings):
        content = gzip.compress(content, mtime=0)
        headers["Content-Encoding"] = "gzip"
    return content, headers


def accepts_gzip(value: str) -> bool:
    """Honor explicit gzip quality values ahead of a wildcard fallback.

    Args:
        value: The request's Accept-Encoding field.

    Returns:
        Whether gzip is permitted with a valid positive quality value.
    """
    qualities = {}
    for entry in value.lower().split(","):
        coding, *parameters = entry.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            key, _, raw = parameter.strip().partition("=")
            if key == "q":
                try:
                    quality = float(raw)
                except ValueError:
                    quality = 0.0
        qualities[coding.strip()] = quality if 0 <= quality <= 1 else 0.0
    return qualities.get("gzip", qualities.get("*", 0)) > 0
