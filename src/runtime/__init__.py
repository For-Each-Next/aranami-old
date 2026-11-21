"""Manage report workflows and centrally prepared website data.

Toolforge runs the grouped collection and report jobs via
``python -m runtime.services``.
Call :func:`run` to start the scheduled WikiProject Video games
monitor, with an immediate check of all reports on a fresh start in live
or preview mode. Pass ``run_immediately=False`` to wait for scheduled
times.
Call :func:`run_once` to execute selected reports immediately,
with an optional date anchor. Both default to live publication; pass
``dry=True`` to write previews instead of wiki edits.
"""

__all__ = ("run", "run_once")
lazy from runtime.scheduling.runner import run, run_once
