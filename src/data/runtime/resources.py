"""Validate saved environment and resource observations.

Readers accept explicit bounded facts without sampling the host system.
"""

import math

from shared.support.resources import MAX_TEXT

_TEXT_FIELDS = {"python", "system", "machine"}
_OPTIONAL_TEXT_FIELDS = {
    "os_release",
    "kernel",
    "python_implementation",
    "python_compiler",
    "aranami_version",
    "aranami_built_at",
}
_NUMBER_FIELDS = {
    "memory_bytes",
    "memory_limit_bytes",
    "cpu_percent",
    "cpu_limit",
}
_STORAGE_FIELDS = {"storage_used_bytes", "storage_total_bytes"}


def validate_runtime(value: object) -> dict[str, object] | None:
    """Validate optional saved environment and resource observations.

    Args:
        value: Runtime object from a bounded schedule snapshot.

    Returns:
        A copied runtime object, or none for an absent observation.

    Raises:
        ValueError: A field, string, or measurement is invalid.
    """
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or not set(value) >= _TEXT_FIELDS | _NUMBER_FIELDS
        or set(value)
        - (
            _TEXT_FIELDS
            | _OPTIONAL_TEXT_FIELDS
            | _NUMBER_FIELDS
            | _STORAGE_FIELDS
        )
    ):
        message = "Invalid server runtime fields."
        raise ValueError(message)
    for key in _TEXT_FIELDS | _OPTIONAL_TEXT_FIELDS:
        text = value.get(key)
        if key in _OPTIONAL_TEXT_FIELDS and text is None:
            continue
        if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
            message = "Invalid server environment value."
            raise ValueError(message)
    _validate_numbers(value, _NUMBER_FIELDS | _STORAGE_FIELDS)
    return dict(value)


def validate_usage(value: object) -> dict[str, object]:
    """Validate only the four container counters used by scheduled jobs.

    Returns:
        A copy of the observed counters, including explicit unknowns.

    Raises:
        ValueError: A counter is missing or invalid.
    """
    if not isinstance(value, dict) or value.keys() != _NUMBER_FIELDS:
        message = "Invalid container resource fields."
        raise ValueError(message)
    _validate_numbers(value, _NUMBER_FIELDS)
    return dict(value)


def _validate_numbers(value: dict, fields: set[str]) -> None:
    """Accept nonnegative finite quantities and whole-byte counters.

    Raises:
        ValueError: A quantity or its unit is invalid.
    """
    for key in fields:
        number = value.get(key)
        if number is None:
            continue
        if (
            type(number) not in {int, float}
            or not math.isfinite(number)
            or not 0 <= number < 2**63
        ):
            message = "Invalid server resource measurement."
            raise ValueError(message)
        if key.endswith("_bytes") and type(number) is not int:
            message = "Server memory counters must be whole bytes."
            raise ValueError(message)
