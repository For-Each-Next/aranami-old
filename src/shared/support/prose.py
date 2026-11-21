"""Extract readable prose from wikitext using an explicit profile.

Call ``extract_prose`` with a site's section and template rules. The
extractor has no knowledge of article assessments or Wikipedia language
conventions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import mwparserfromhell
from mwparserfromhell.definitions import is_visible
from mwparserfromhell.nodes import (
    Argument,
    ExternalLink,
    Heading,
    HTMLEntity,
    Tag,
    Text,
    Wikilink,
)

from shared.support.templates import template_page
from shared.support.wikitext import (
    COMMENT_RE,
    REF_RE,
    SELF_CLOSING_REF_RE,
    TAG_RE,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mwparserfromhell.nodes import Node
    from mwparserfromhell.wikicode import Wikicode
    from pywikibot.site import BaseSite

_HEADING_RE = re.compile(r"^=+\s*(.*?)\s*=+\s*$")
_EXTRA_LINES = re.compile(r"\n{3,}")
_CLEANUP = (
    (COMMENT_RE, " "),
    (REF_RE, " "),
    (SELF_CLOSING_REF_RE, " "),
    (TAG_RE, " "),
    (re.compile(r"\[\["), ""),
    (re.compile(r"\]\]"), ""),
    (re.compile(r"\{\{"), " "),
    (re.compile(r"\}\}"), " "),
    (re.compile(r"[|!*#;:]"), " "),
    (re.compile(r"\s+"), " "),
)


@dataclass(frozen=True, slots=True)
class ProseProfile:
    """Configure sections and template parameters that contain prose.

    Attributes:
        non_prose_headings: Case-folded headings marking the start of
            trailing content to exclude.
        prose_templates: Template titles whose matching parameters
            contain prose.
        prose_parameters: Pattern matching prose parameter names after
            removing underscores, spaces, and hyphens. None disables
            special parameter extraction.
    """

    non_prose_headings: frozenset[str] = frozenset()
    prose_templates: frozenset[str] = frozenset()
    prose_parameters: re.Pattern[str] | None = None


def _strip_tail(
    text: str,
    profile: ProseProfile,
    *,
    wikitext: bool,
    positions: list[int] | None = None,
) -> str:
    """Remove trailing sections and retain optional source offsets.

    Returns:
        The kept lines, separated by newlines.
    """
    lines = text.splitlines()
    kept = []
    for line in lines:
        if wikitext:
            match = _HEADING_RE.match(line.strip())
            heading = match.group(1).strip().casefold() if match else None
        else:
            heading = line.strip().casefold().strip(":")
        if heading in profile.non_prose_headings:
            break
        kept.append(line)
    if positions is not None:
        retained, start = [], 0
        for index, (line, original) in enumerate(
            zip(kept, text.splitlines(keepends=True), strict=False),
        ):
            if index:
                retained.append(-1)
            retained.extend(positions[start : start + len(line)])
            start += len(original)
        positions[:] = retained
    return "\n".join(kept)


def _substitute(
    text: str,
    pattern: re.Pattern[str],
    value: str,
    positions: list[int] | None,
) -> str:
    """Apply cleanup and mark new separators as unowned.

    Returns:
        The text after substitution.
    """
    if positions is not None:
        kept, start = [], 0
        for match in pattern.finditer(text):
            kept.extend(positions[start : match.start()])
            kept.extend([-1] * len(value))
            start = match.end()
        kept.extend(positions[start:])
        positions[:] = kept
    return pattern.sub(value, text)


def _trim(
    text: str,
    positions: list[int] | None,
    characters: str | None = None,
) -> str:
    """Trim a fragment and retain matching source offsets.

    Returns:
        The stripped text.
    """
    stripped = text.strip(characters)
    if positions is not None:
        start = len(text) - len(text.lstrip(characters))
        positions[:] = positions[start : start + len(stripped)]
    return stripped


def _clean_text(text: str, positions: list[int] | None = None) -> str:
    """Remove leftover markup and normalize whitespace for counting.

    Returns:
        Countable text with consistent spaces.
    """
    for pattern, value in _CLEANUP:
        text = _substitute(text, pattern, value, positions)
    return _trim(text, positions)


def _parameter_values(
    code: Wikicode,
    site: BaseSite,
    profile: ProseProfile,
    *,
    include_all: bool,
) -> Iterator[Wikicode]:
    """Select prose parameters in extraction order.

    Yields:
        Configured prose values first, then all values if requested.
    """
    if profile.prose_parameters is None and not include_all:
        return
    templates = code.filter_templates(recursive=True)
    if profile.prose_parameters is not None:
        aliases = {
            page
            for alias in profile.prose_templates
            if (page := template_page(alias, site)) is not None
        }
        for template in templates:
            if template_page(template.name, site) in aliases:
                for parameter in template.params:
                    name = re.sub(r"[_ -]+", "", str(parameter.name).strip())
                    if profile.prose_parameters.fullmatch(name):
                        yield parameter.value
    if include_all:
        for template in templates:
            for parameter in template.params:
                yield parameter.value


def _children(node: Node) -> Iterator[tuple[Wikicode, int]]:
    """Locate parser children in source order.

    Yields:
        Each child and its offset, including repeated values.
    """
    source = str(node)
    cursor = 0
    for child in node.__children__():
        text = str(child)
        start = source.index(text, cursor)
        yield child, start
        cursor = start + len(text)


def _visible_child(node: Node) -> Wikicode | None:
    """Mirror the parser's strip-code selection.

    Returns:
        The visible child when the node displays one.
    """
    match node:
        case Heading(title=title):
            return title
        case Wikilink(title=title, text=label):
            return title if label is None else label
        case ExternalLink(url=url, title=title, brackets=brackets):
            return title if brackets else url
        case Argument(default=default):
            return default
        case Tag(tag=tag, contents=contents) if is_visible(str(tag)):
            return contents
        case _:
            return None


def _visible_at(
    code: Wikicode,
    source_positions: list[int],
    start: int = 0,
) -> tuple[str, list[int]]:
    """Carry source offsets through the visible-text projection.

    Returns:
        Visible text and its original source offsets.
    """
    chunks, positions = [], []
    for node in code.nodes:
        size = len(str(node))
        if isinstance(node, Text):
            chunks.append(str(node))
            positions.extend(source_positions[start : start + size])
        elif isinstance(node, HTMLEntity):
            value = node.normalize()
            chunks.append(value)
            positions.extend([source_positions[start]] * len(value))
        elif visible := _visible_child(node):
            for child, offset in _children(node):
                if child is visible:
                    value, origins = _visible_at(
                        child,
                        source_positions,
                        start + offset,
                    )
                    chunks.append(value)
                    positions.extend(origins)
                    break
        start += size
    value = _trim("".join(chunks), positions, "\n")
    return _substitute(value, _EXTRA_LINES, "\n\n", positions), positions


def _parameter_offsets(
    code: Wikicode,
    offsets: dict[int, int],
    targets: set[int],
    start: int = 0,
) -> None:
    """Find the source offsets of selected parameter values."""
    for node in code.nodes:
        for child, offset in _children(node):
            position = start + offset
            if id(child) in targets:
                offsets[id(child)] = position
            _parameter_offsets(child, offsets, targets, position)
        start += len(str(node))


def _prose_parts(
    code: Wikicode,
    parameters: list[Wikicode],
    profile: ProseProfile,
    source_positions: list[int] | None,
) -> Iterator[tuple[str, list[int] | None]]:
    """Project ordinary prose and selected template fragments.

    Yields:
        Extracted fragments with optional original offsets.

    Raises:
        ValueError: The selected source positions cannot be established.
    """
    visible = code.strip_code(normalize=True, collapse=True)
    origins = None
    offsets = {}
    if source_positions is not None:
        projected, origins = _visible_at(code, source_positions)
        if projected != visible or len(origins) != len(visible):
            message = "Could not match prose to original source offsets."
            raise ValueError(message)
        if parameters:
            _parameter_offsets(
                code,
                offsets,
                {id(value) for value in parameters},
            )
    yield (
        _strip_tail(
            visible,
            profile,
            wikitext=False,
            positions=origins,
        ),
        origins,
    )
    for value in parameters:
        text = str(value)
        origins = None
        if source_positions is not None:
            if id(value) not in offsets:
                message = "Could not locate a selected prose parameter."
                raise ValueError(message)
            start = offsets[id(value)]
            origins = source_positions[start : start + len(text)]
        yield _clean_text(text, origins), origins


def extract_prose(
    text: str,
    *,
    site: BaseSite,
    profile: ProseProfile,
    include_template_values: bool = False,
    source_offsets: list[int] | None = None,
) -> str:
    """Extract countable prose using caller-supplied section rules.

    Template values are normally hidden except for parameters selected
    by the profile. Enabling all template values includes every readable
    value. Identical extracted fragments appear only once.

    Args:
        text: Complete source wikitext.
        site: Site providing template namespace and title rules.
        profile: Trailing section and embedded prose rules.
        include_template_values: Include readable values from all
            templates, in addition to the profile's selected values.
        source_offsets: Output list for the original positions of prose.
            Inserted whitespace has position -1.

    Returns:
        Whitespace-normalized prose without structural markup.
    """
    positions = list(range(len(text))) if source_offsets is not None else None
    code = mwparserfromhell.parse(
        _strip_tail(text, profile, wikitext=True, positions=positions),
    )
    parameters = list(
        _parameter_values(
            code,
            site,
            profile,
            include_all=include_template_values,
        ),
    )
    unique = {}
    for part, origins in _prose_parts(code, parameters, profile, positions):
        if part := _trim(part, origins):
            unique.setdefault(part, origins)
    if source_offsets is not None:
        source_offsets[:] = [
            position
            for index, origins in enumerate(unique.values())
            for position in ([-1] if index else []) + origins
        ]
    return _clean_text("\n".join(unique), source_offsets)
