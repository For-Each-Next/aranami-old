"""Cache rendered pages briefly without writing runtime files."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webservice.redis_page_cache import RedisPageCache

_MAX_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 32
_MAX_AGE = 60


@dataclass(frozen=True, slots=True)
class _Entry:
    """Retain one document alongside its source identity and expiry."""

    identity: tuple
    expires_at: float
    content: str
    size: int


class PageCache:
    """Reuse rendered documents until expiry or input changes."""

    def __init__(self, shared: RedisPageCache | None = None) -> None:
        """Start a local cache with optional shared storage."""
        self._shared = shared
        self._entries: OrderedDict[tuple, _Entry] = OrderedDict()
        self._bytes = 0
        self._lock = Lock()

    def get(
        self,
        key: tuple,
        identity: tuple,
        *,
        shared: bool = False,
    ) -> str | None:
        """Return a fresh document for the exact current input identity.

        Args:
            key: Page route, normalized query, and selected locale.
            identity: Current metadata of all saved input files.
            shared: Permit Redis reuse for a bounded prepared variant.

        Returns:
            Cached HTML, or None when it must be rendered again.
        """
        with self._lock:
            self._expire(time.monotonic())
            entry = self._entries.pop(key, None)
            if entry is not None:
                if entry.identity == identity:
                    self._entries[key] = entry
                    return entry.content
                self._bytes -= entry.size
        if shared and self._shared is not None:
            cached = self._shared.read(key, identity)
            if cached is not None:
                content, seconds = cached
                self._remember(key, identity, content, seconds)
                return content
        return None

    def put(
        self,
        key: tuple,
        identity: tuple,
        content: str,
        *,
        shared: bool = False,
    ) -> None:
        """Retain a document within fixed byte and entry bounds.

        Args:
            key: Page route, normalized query, and selected locale.
            identity: Input metadata captured before rendering.
            content: Fully escaped document ready for delivery.
            shared: Store this bounded prepared variant in Redis.
        """
        self._remember(key, identity, content, _MAX_AGE)
        if shared and self._shared is not None:
            self._shared.put(key, identity, content)

    def _remember(
        self,
        key: tuple,
        identity: tuple,
        content: str,
        seconds: float,
    ) -> None:
        """Keep a document locally within its expiry and limits."""
        size = len(content.encode("utf-8"))
        with self._lock:
            self._expire(time.monotonic())
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= old.size
            if size > _MAX_BYTES:
                return
            while self._entries and (
                self._bytes + size > _MAX_BYTES
                or len(self._entries) >= _MAX_ENTRIES
            ):
                self._bytes -= self._entries.popitem(last=False)[1].size
            self._entries[key] = _Entry(
                identity,
                time.monotonic() + seconds,
                content,
                size,
            )
            self._bytes += size

    def close(self) -> None:
        """Release the shared cache's connections."""
        if self._shared is not None:
            self._shared.close()

    def expire(self) -> None:
        """Release expired documents even when no page is requested."""
        with self._lock:
            self._expire(time.monotonic())

    def _expire(self, now: float) -> None:
        """Drop every expired entry while the cache lock is held."""
        expired = [
            key
            for key, entry in self._entries.items()
            if now >= entry.expires_at
        ]
        for key in expired:
            self._bytes -= self._entries.pop(key).size
