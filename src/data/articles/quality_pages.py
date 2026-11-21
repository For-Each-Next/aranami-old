"""Retain prepared article-statistics pages for direct HTTP delivery.

Background presentation writes one bounded JSON document per preset.
The total budget accommodates many resources, each with its own limit.
Readers never calculate statistics or invoke a renderer.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from typing import TYPE_CHECKING

from polars.exceptions import PolarsError

if TYPE_CHECKING:
    from pathlib import Path

from data.prepared import read_values, values_path
from shared.support.files import atomic_json, encode_json, file_identity

MAX_BYTES = 32 * 1024 * 1024
_MAX_RESOURCE_BYTES = 16 * 1024 * 1024
AUTHOR_DETAIL_NAME = re.compile(
    r"author-[1-9][0-9]{0,9}(?:-significant)?\.html",
)
HASHED_AUTHOR_DETAIL_NAME = re.compile(
    r"author-quality-author-[1-9][0-9]*(?:-significant)?-[0-9a-f]{64}\.html",
)
_PACKED_RESOURCE_PREFIX = "zlib:"
_RESOURCE_NAME = re.compile(
    r"(?:(?:catalog|directory)-[0-9a-f]{64}\.json|"
    rf"{HASHED_AUTHOR_DETAIL_NAME.pattern}|"
    rf"{AUTHOR_DETAIL_NAME.pattern})",
)


def path_for(
    runtime: Path,
    locale: str,
    *,
    basis: str,
    all_grades: bool = False,
) -> Path:
    """Locate a validated flat presentation preset.

    Returns:
        One file under the webservice data directory.

    Raises:
        ValueError: A preset contains an unsupported value.
    """
    if locale not in {"en", "zh-hans", "zh-hant"} or basis not in {
        "current",
        "listed",
    }:
        message = "Unsupported quality-page preset."
        raise ValueError(message)
    cohort = "all" if all_grades else "0"
    return (
        runtime
        / "data/webservice"
        / f"quality-page-{locale}-{cohort}-{basis}.json"
    )


def identity(path: Path) -> tuple:
    """Observe a saved preset without decoding its contents.

    Returns:
        Atomic-file identity, or an explicit missing identity.
    """
    return file_identity(values_path(path)) or (None,)


def read(path: Path, *, browser: bool = False) -> str | None:
    """Read the preferred prepared document without source reads.

    Returns:
        Vue or native HTML from the latest successful preparation.
    """
    value = _read_bundle(path)
    if value is None:
        return None
    document = (
        value.get("browser", value["html"]) if browser else value["html"]
    )
    return (
        _unpack_resource(document)
        if document.startswith(_PACKED_RESOURCE_PREFIX)
        else document
    )


def _read_bundle(path: Path) -> dict | None:
    """Validate one atomic HTML and resource generation.

    Returns:
        The saved bundle, or None when preparation has not completed.

    Raises:
        ValueError: The saved schema or payload is invalid.
    """
    try:
        value = read_values(path, MAX_BYTES)
    except FileNotFoundError:
        return None
    if (
        value.get("schema") not in {1, 2}
        or not isinstance(
            value.get("html"),
            str,
        )
        or ("browser" in value and not isinstance(value["browser"], str))
    ):
        message = "Invalid prepared quality page."
        raise ValueError(message)
    for key in ("resources", "previous_resources"):
        resources = value.get(key, {})
        if not isinstance(resources, dict) or any(
            not _RESOURCE_NAME.fullmatch(name) or not isinstance(content, str)
            for name, content in resources.items()
        ):
            message = "Invalid prepared quality resources."
            raise ValueError(message)
    return value


def read_resource(path: Path, name: str) -> str | None:
    """Read a resource by its exact digest or current account identity.

    Returns:
        A matching catalog or detail page, or None for an expired URL.

    Raises:
        ValueError: Saved content no longer matches its URL digest.
    """
    if not _RESOURCE_NAME.fullmatch(name):
        return None
    value = _read_bundle(path)
    if value is None:
        return None
    content = value.get("resources", {}).get(name)
    current_author = bool(AUTHOR_DETAIL_NAME.fullmatch(name))
    if content is None and not current_author:
        content = value.get("previous_resources", {}).get(name)
    if content is not None:
        if content.startswith(_PACKED_RESOURCE_PREFIX):
            content = _unpack_resource(content)
        if current_author:
            return content
        expected = name.rsplit("-", 1)[1].split(".", 1)[0]
        if hashlib.sha256(content.encode()).hexdigest() != expected:
            message = "Prepared quality resource digest mismatch."
            raise ValueError(message)
    return content


def _unpack_resource(content: str) -> str:
    """Decode a compressed page resource within the storage bound.

    Returns:
        The original UTF-8 data.

    Raises:
        ValueError: The resource cannot be decoded within its bound.
    """
    message = "Invalid compressed quality resource."
    try:
        encoded = b64decode(
            content.removeprefix(_PACKED_RESOURCE_PREFIX),
            validate=True,
        )
        stream = zlib.decompressobj()
        raw = stream.decompress(encoded, _MAX_RESOURCE_BYTES + 1)
        if (
            len(raw) > _MAX_RESOURCE_BYTES
            or not stream.eof
            or stream.unused_data
        ):
            raise ValueError(message)
        return raw.decode()
    except (Base64Error, zlib.error, UnicodeDecodeError) as error:
        raise ValueError(message) from error


def _pack_resource(content: str) -> str:
    """Compress resources without changing their served bytes.

    Returns:
        The smaller of the compressed and original representations.

    Raises:
        ValueError: The resource exceeds the bounded storage size.
    """
    raw = content.encode()
    if len(raw) > _MAX_RESOURCE_BYTES:
        message = "The quality resource exceeds its size limit."
        raise ValueError(message)
    packed = _PACKED_RESOURCE_PREFIX + b64encode(
        zlib.compress(raw),
    ).decode("ascii")
    return packed if len(packed) < len(raw) else content


def save(
    path: Path,
    html: str,
    source: tuple,
    *,
    resources: dict[str, str] | None = None,
    browser: str | None = None,
) -> None:
    """Atomically select HTML and resources with one prior generation.

    Previous resources survive ordinary refreshes for in-flight pages.
    They are optional if retaining them would exceed the existing bound.
    """
    value = {"schema": 1, "source": list(source), "html": _pack_resource(html)}
    if browser is not None:
        value["browser"] = _pack_resource(browser)
    if resources is not None:
        resources = {
            name: _pack_resource(content)
            for name, content in resources.items()
        }
        value.update(schema=2, resources=resources)
        try:
            previous = _read_bundle(path)
        except OSError, ValueError, PolarsError:
            previous = None
        if previous:
            old_resources = previous.get("resources", {})
            value["previous_resources"] = (
                previous.get("previous_resources", {})
                if old_resources == resources
                else {
                    name: content
                    for name, content in old_resources.items()
                    if not AUTHOR_DETAIL_NAME.fullmatch(name)
                }
            )
            if len(encode_json(value)) > MAX_BYTES:
                value.pop("previous_resources")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value, max_bytes=MAX_BYTES)
