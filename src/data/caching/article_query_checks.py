"""Exchange bounded, temporary title checks with the query worker."""

from __future__ import annotations

import hmac
import json
import os
import time
from contextlib import suppress
from typing import TYPE_CHECKING, TypedDict

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from shared.article_query import PROJECTS, valid_title_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

_QUEUE_LIMIT = 384
_QUEUE_BATCH = 96
_QUEUE_TTL = 3 * 3600
_RESULT_TTL = 3 * 3600
_MAX_RESULT_BYTES = 12 * 1024
_SIGNATURE_BYTES = 32

type CheckKey = tuple[str, str]


class TitleCheck(TypedDict):
    """Carry exact observations and verified alternative targets."""

    titles: dict[str, tuple[int | None, str | None]]
    variants: list[str]


class TitleChecks:
    """Keep uncached title requests outside durable runtime state."""

    def __init__(self, client: Redis, secret: bytes, runtime: Path) -> None:
        """Bind temporary keys to the tool and runtime."""
        self._client = client
        self._secret = secret
        token = self._sign(str(runtime).encode()).hex()
        self._namespace = f"aranami:article-query:v1:{token}"
        self._queue = f"{self._namespace}:pending"

    @classmethod
    def from_environment(cls, runtime: Path) -> TitleChecks | None:
        """Configure the shared cache without connecting at startup.

        Returns:
            A cache using the existing Redis URL and signing secret.
        """
        url = os.environ.get("TOOL_REDIS_URI")
        if not url:
            return None
        try:
            secret = bytes.fromhex(os.environ.get("ARANAMI_REDIS_SECRET", ""))
            if len(secret) != _SIGNATURE_BYTES:
                return None
            client = Redis.from_url(
                url,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                max_connections=4,
                protocol=2,
                retry=Retry(NoBackoff(), 0),
            )
        except TypeError, ValueError:
            return None
        return cls(client, secret, runtime)

    def _sign(self, value: bytes) -> bytes:
        """Authenticate a shared cache observation.

        Returns:
            The tool-private signature.
        """
        return hmac.digest(self._secret, value, "sha256")

    def _result_key(self, key: CheckKey) -> str:
        """Name the result slot for an exact lookup.

        Returns:
            A private Redis key for this site and title.
        """
        token = self._sign(_encode(key)).hex()
        return f"{self._namespace}:answer:{token}"

    def read(self, keys: Iterable[CheckKey]) -> dict[CheckKey, TitleCheck]:
        """Read confirmed checks in one Redis round trip.

        Returns:
            Authenticated results for the observed site and title keys.
        """
        unique = list(dict.fromkeys(keys))
        if not unique:
            return {}
        try:
            with self._client.pipeline(transaction=False) as pipe:
                for key in unique:
                    pipe.getrange(self._result_key(key), 0, _MAX_RESULT_BYTES)
                responses = pipe.execute()
        except RedisError:
            return {}
        result = {}
        for key, value in zip(unique, responses, strict=True):
            if not isinstance(value, bytes) or not (
                _SIGNATURE_BYTES < len(value) <= _MAX_RESULT_BYTES
            ):
                continue
            proof, body = value[:_SIGNATURE_BYTES], value[_SIGNATURE_BYTES:]
            if not hmac.compare_digest(proof, self._sign(_encode(key) + body)):
                continue
            decoded = json.loads(body)
            result[key] = decoded
        return result

    def request(self, keys: Iterable[CheckKey]) -> None:
        """Coalesce misses into a bounded, oldest-first queue."""
        now = time.time()
        pending = {
            _encode(key): now
            for key in keys
            if key[0] in PROJECTS and valid_title_key(key[1])
        }
        if not pending:
            return
        try:
            with self._client.pipeline() as pipe:
                pipe.zadd(self._queue, pending, nx=True)
                pipe.zremrangebyrank(self._queue, _QUEUE_LIMIT, -1)
                pipe.expire(self._queue, _QUEUE_TTL)
                pipe.execute()
        except RedisError:
            return

    def pending(self) -> list[CheckKey]:
        """Read the next batch and retain it until a result is saved.

        Returns:
            The oldest valid requests, or none on a cache failure.
        """
        try:
            rows = self._client.zrange(self._queue, 0, _QUEUE_BATCH - 1)
        except RedisError:
            return []
        return [key for row in rows if (key := _decode(row)) is not None]

    def complete(self, results: Mapping[CheckKey, TitleCheck]) -> None:
        """Cache results and clear their requests in one transaction."""
        if not results:
            return
        with suppress(RedisError), self._client.pipeline() as pipe:
            for key, value in results.items():
                body = json.dumps(value, ensure_ascii=False).encode()
                saved = self._sign(_encode(key) + body) + body
                if len(saved) <= _MAX_RESULT_BYTES:
                    pipe.set(self._result_key(key), saved, ex=_RESULT_TTL)
                    pipe.zrem(self._queue, _encode(key))
            pipe.execute()


def _encode(key: CheckKey) -> bytes:
    """Serialize the literal title lookup.

    Returns:
        A stable Redis queue member for the exact site and title.
    """
    return json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()


def _decode(source: bytes) -> CheckKey | None:
    """Validate a queued key before making an indexed read.

    Returns:
        The validated site and title, or none for malformed input.
    """
    try:
        value = json.loads(source[:1024])
    except ValueError, RecursionError:
        return None
    match value:
        case [str() as site, str() as key]:
            return (
                (site, key)
                if site in PROJECTS and valid_title_key(key)
                else None
            )
        case _:
            return None
