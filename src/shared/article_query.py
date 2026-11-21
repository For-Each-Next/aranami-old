"""Parse the bounded Article List expression language."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Literal, TypedDict

from shared.config import PROJECT_DATA_SCOPES

PROJECTS = dict(PROJECT_DATA_SCOPES)
MAX_QUERY_BYTES = 2048
MAX_CATEGORY_DEPTH = 5
MAX_TITLE_BYTES = 255
_MAX_NESTING = 12
_MAX_TERMS = 24
_MAX_VALUES = 48
_MAX_NUMBER_LENGTH = 3
_MAX_NAMESPACE = 10_000
_FIRST_PRINTABLE = 32
_SYMBOL = re.compile(r"[a-z_]+|[0-9]+|[(){}&,|~=]")
_DECODER = json.JSONDecoder()
PAGE_PREDICATES = frozenset({"cat", "tl", "link", "backlink"})
ASSESSMENT_PREDICATES = frozenset({"class", "imp", "wp"})
_OPTIONS = {
    "cat": {"site", "on", "depth"},
    "tl": {"site", "on"},
    "link": {"site", "on"},
    "backlink": {"site", "on"},
    "wp": {"site", "class", "importance"},
    "class": {"site", "project"},
    "imp": {"site", "project"},
    "has_wiki": set(),
}
_NAMESPACES = {
    "Talk": 1,
    "User": 2,
    "User talk": 3,
    "Wikipedia": 4,
    "WP": 4,
    "Project": 4,
    "WikiProject": 4,
    "Wikipedia talk": 5,
    "File": 6,
    "Image": 6,
    "File talk": 7,
    "MediaWiki": 8,
    "MediaWiki talk": 9,
    "Template": 10,
    "Template talk": 11,
    "Help": 12,
    "Help talk": 13,
    "Category": 14,
    "Category talk": 15,
    "Portal": 100,
    "Portal talk": 101,
    "Draft": 118,
    "Draft talk": 119,
    "Module": 828,
    "Module talk": 829,
}
_CHINESE_NAMESPACES = {
    "讨论": 1,
    "討論": 1,
    "对话": 1,
    "對話": 1,
    "用户": 2,
    "用戶": 2,
    "用户讨论": 3,
    "用戶討論": 3,
    "用户对话": 3,
    "用戶對話": 3,
    "维基百科": 4,
    "維基百科": 4,
    "维基百科讨论": 5,
    "維基百科討論": 5,
    "文件": 6,
    "档案": 6,
    "檔案": 6,
    "图像": 6,
    "圖像": 6,
    "模板": 10,
    "模版": 10,
    "模板讨论": 11,
    "模板討論": 11,
    "帮助": 12,
    "幫助": 12,
    "分类": 14,
    "分類": 14,
    "分类讨论": 15,
    "分類討論": 15,
    "主题": 100,
    "主題": 100,
    "草稿": 118,
    "模块": 828,
    "模組": 828,
}
_EN_NAMES = {label.casefold(): ns for label, ns in _NAMESPACES.items()}
_NS_LABELS = {number: title for title, number in reversed(_NAMESPACES.items())}
_DEFAULT_NS = {"cat": 14, "tl": 10}

type Argument = str | int | list[str]


class Predicate(TypedDict):
    """Represent a validated term and its source positions."""

    op: Literal["term"]
    name: str
    value: str | list[str]
    options: dict[str, Argument]
    start: int
    end: int


class Group(TypedDict):
    """Represent a logical operator and its ordered children."""

    op: Literal["and", "or", "not"]
    children: list[Expression]


type Expression = Predicate | Group


class QuerySyntaxError(ValueError):
    """Identify an invalid expression at a character offset."""

    def __init__(self, message: str, offset: int) -> None:
        """Record the position for the block and text editors."""
        super().__init__(message)
        self.offset = offset


def _text(value: object) -> bool:
    """Check a Unicode argument.

    Returns:
        Whether the input is bounded, nonempty text without controls.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return len(value.encode()) <= MAX_TITLE_BYTES and all(
            ord(char) >= _FIRST_PRINTABLE for char in value
        )
    except UnicodeEncodeError:
        return False


def values(value: Argument) -> list[str]:
    """Expand a predicate value.

    Returns:
        The alternatives to match in order.
    """
    return value if isinstance(value, list) else [str(value)]


def title_key(site: str, kind: str, text: str) -> str:
    """Normalize an entered title to the namespace and database title.

    Returns:
        A namespace-qualified key with the literal script retained.
    """
    text = unicodedata.normalize("NFC", text.split("#", 1)[0])
    text = " ".join(text.replace("_", " ").strip().lstrip(":").split())
    prefix, separator, suffix = text.partition(":")
    namespace = _DEFAULT_NS.get(kind, 0)
    if separator:
        name = prefix.strip().casefold()
        number = _EN_NAMES.get(name)
        if number is None and site == "zh":
            number = _CHINESE_NAMESPACES.get(name)
        if number is not None:
            namespace, text = number, suffix.strip()
    first = text[:1].upper()
    if len(first) == 1:
        text = first + text[1:]
    return f"{namespace}:{text.replace(' ', '_')}"


def key_parts(key: str) -> tuple[int, str]:
    """Split a validated key into its two title components.

    Returns:
        The namespace number and exact database title.
    """
    number, title = key.split(":", 1)
    return int(number), title


def valid_title_key(key: str) -> bool:
    """Validate input for an indexed MediaWiki lookup.

    Returns:
        Whether the namespace and database title are within bounds.
    """
    try:
        namespace, title = key_parts(key)
    except ValueError:
        return False
    return 0 <= namespace < _MAX_NAMESPACE and _text(title)


def title_label(key: str) -> str:
    """Format a title key for display or source title resolution.

    Returns:
        A title with its namespace prefix when applicable.
    """
    namespace, title = key_parts(key)
    title = title.replace("_", " ")
    name = _NS_LABELS.get(namespace, str(namespace))
    return f"{name}:{title}" if namespace else title


def _valid_options(name: str, options: dict[str, Argument]) -> bool:
    """Validate the allowed settings for one predicate.

    Returns:
        Whether the keywords and values are supported.
    """
    site = options.get("site", "zh")
    depth = options.get("depth", 0)
    on = options.get("on", "main")
    return (
        isinstance(site, str)
        and site in PROJECTS
        and isinstance(on, str)
        and on in {"main", "talk"}
        and type(depth) is int
        and 0 <= depth <= MAX_CATEGORY_DEPTH
        and ("project" not in options or _text(options["project"]))
        and all(
            isinstance(options[key], (str, list))
            for key in ("class", "importance")
            if key in options
        )
        and options.keys() <= _OPTIONS[name]
    )


class _Parser:
    """Read operator precedence and arguments from left to right."""

    def __init__(self, source: str) -> None:
        """Track characters and the structural work budget."""
        self.source = source
        self.position = 0
        self.terms = 0
        self.string_count = 0

    def _skip_space(self) -> int:
        """Skip whitespace before the next token.

        Returns:
            The start of the next token or the end of the query.
        """
        while (
            self.position < len(self.source)
            and self.source[self.position].isspace()
        ):
            self.position += 1
        return self.position

    def _take(self, char: str) -> bool:
        """Look for a punctuation token.

        Returns:
            Whether the token was present and consumed.
        """
        if self.source.startswith(char, self._skip_space()):
            self.position += 1
            return True
        return False

    def _require(self, char: str) -> None:
        """Require the next punctuation token.

        Raises:
            QuerySyntaxError: The expected character is absent.
        """
        if not self._take(char):
            message = f"Expected {char!r}."
            raise QuerySyntaxError(message, self.position)

    def _token(self) -> str:
        """Read the next bare token.

        Returns:
            The name, integer text or punctuation.

        Raises:
            QuerySyntaxError: The input has no token here.
        """
        if match := _SYMBOL.match(self.source, self._skip_space()):
            self.position = match.end()
            return match[0]
        message = "Expected a token."
        raise QuerySyntaxError(message, self.position)

    def _string(self) -> str:
        """Decode a JSON-style quoted string.

        Returns:
            The decoded and validated Unicode argument.

        Raises:
            QuerySyntaxError: The string is malformed or out of bounds.
        """
        start = self._skip_space()
        if not self.source.startswith('"', start):
            message = "Expected a quoted string."
            raise QuerySyntaxError(message, start)
        try:
            value, self.position = _DECODER.raw_decode(self.source, start)
        except json.JSONDecodeError as error:
            message = "Invalid quoted string."
            raise QuerySyntaxError(message, error.pos) from error
        self.string_count += 1
        if self.string_count > _MAX_VALUES or not _text(value):
            message = "Invalid or oversized value."
            raise QuerySyntaxError(message, start)
        return value

    def _argument(self) -> Argument:
        """Read one predicate argument.

        Returns:
            A string, integer or nonempty set of strings.

        Raises:
            QuerySyntaxError: The argument has an unsupported form.
        """
        if self._take("{"):
            items = [self._string()]
            while self._take(","):
                items.append(self._string())
            self._require("}")
            return list(dict.fromkeys(items))
        if self.source.startswith('"', self._skip_space()):
            return self._string()
        start = self.position
        token = self._token()
        if token.isdecimal() and len(token) <= _MAX_NUMBER_LENGTH:
            return int(token)
        message = "Expected a string, set or integer."
        raise QuerySyntaxError(message, start)

    def _predicate(self) -> Predicate:
        """Read one condition and validate its options.

        Returns:
            A condition with its exact source span.

        Raises:
            QuerySyntaxError: A term or keyword breaks the grammar.
        """
        start = self._skip_space()
        name = self._token()
        self.terms += 1
        if name not in _OPTIONS or self.terms > _MAX_TERMS:
            message = "Unknown predicate or too many terms."
            raise QuerySyntaxError(message, start)
        self._require("(")
        value = self._argument()
        if type(value) is int or (
            name == "has_wiki"
            and (not isinstance(value, str) or value not in PROJECTS)
        ):
            message = "Invalid predicate value."
            raise QuerySyntaxError(message, start)
        options = {}
        while self._take(","):
            offset = self._skip_space()
            key = self._token()
            if key in options or key not in _OPTIONS[name]:
                message = "Unknown or repeated option."
                raise QuerySyntaxError(message, offset)
            self._require("=")
            options[key] = self._argument()
        self._require(")")
        if not _valid_options(name, options):
            message = "Invalid predicate options."
            raise QuerySyntaxError(message, start)
        return {
            "op": "term",
            "name": name,
            "value": value,
            "options": options,
            "start": start,
            "end": self.position,
        }

    def _unary(self, depth: int) -> Expression:
        """Read the expression at the highest precedence.

        Returns:
            A predicate, complement or parenthesized group.

        Raises:
            QuerySyntaxError: The nesting limit has been exceeded.
        """
        if depth >= _MAX_NESTING:
            message = "Query nesting is too deep."
            raise QuerySyntaxError(message, self.position)
        if self._take("~"):
            return {"op": "not", "children": [self._unary(depth + 1)]}
        if self._take("("):
            expression = self.disjunction(depth + 1)
            self._require(")")
            return expression
        return self._predicate()

    def _conjunction(self, depth: int) -> Expression:
        """Read predicates joined with AND.

        Returns:
            The conjunction or its single child.
        """
        terms = [self._unary(depth)]
        while self._take("&"):
            terms.append(self._unary(depth))
        return (
            terms[0] if len(terms) == 1 else {"op": "and", "children": terms}
        )

    def disjunction(self, depth: int = 0) -> Expression:
        """Read an expression at the current parenthesis depth.

        Returns:
            The disjunction or its single child.
        """
        terms = [self._conjunction(depth)]
        while self._take("|"):
            terms.append(self._conjunction(depth))
        return terms[0] if len(terms) == 1 else {"op": "or", "children": terms}


def parse(source: str) -> Expression | None:
    """Parse query text into the tree shared by the editors.

    Returns:
        A validated expression, or none for an empty filter.

    Raises:
        QuerySyntaxError: The expression is malformed or too large.
    """
    try:
        size = len(source.encode())
    except UnicodeEncodeError as error:
        message = "Invalid Unicode input."
        raise QuerySyntaxError(message, error.start) from error
    if size > MAX_QUERY_BYTES:
        message = "Query is too long."
        raise QuerySyntaxError(message, 0)
    parser = _Parser(source)
    if parser._skip_space() == len(source):  # ruff: ignore[private-member-access]
        return None
    expression = parser.disjunction()
    if parser._skip_space() != len(source):  # ruff: ignore[private-member-access]
        message = "Unexpected input."
        raise QuerySyntaxError(message, parser.position)
    return expression
