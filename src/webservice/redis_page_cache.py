"""Share authenticated prepared web pages through Toolforge Redis."""

from __future__ import annotations

import hmac
import os
import struct
import time
from typing import TYPE_CHECKING

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from shared.deployment import project_build_time, project_version

if TYPE_CHECKING:
    from pathlib import Path

_TTL_SECONDS = 45
_MAX_BYTES = 512 * 1024
_TIMEOUT_SECONDS = 0.15
_BACKOFF_SECONDS = 20
_SECRET_BYTES = 32
_PROOF_BYTES = 32
_CLOCK = struct.Struct("!d")
_MAX_VALUE = _PROOF_BYTES + _CLOCK.size + _MAX_BYTES


class RedisPageCache:
    """Share prepared public HTML within fixed cache limits."""

    def __init__(self, client: Redis, secret: bytes, namespace: str) -> None:
        """Accept a Redis pool and a tool-private signing key."""
        self._client = client
        self._secret = secret
        self._namespace = namespace.encode()
        self._retry_at = 0.0

    @classmethod
    def from_environment(cls, runtime: Path) -> RedisPageCache | None:
        """Configure the shared cache without contacting Redis.

        Returns:
            A cache when Toolforge provides a URL and signing secret.
        """
        url = os.environ.get("TOOL_REDIS_URI")
        if not url:
            return None
        try:
            secret = bytes.fromhex(os.environ.get("ARANAMI_REDIS_SECRET", ""))
            if len(secret) != _SECRET_BYTES:
                return None
            client = Redis.from_url(
                url,
                socket_connect_timeout=_TIMEOUT_SECONDS,
                socket_timeout=_TIMEOUT_SECONDS,
                protocol=2,
                retry=Retry(NoBackoff(), 0),
                max_connections=4,
            )
        except TypeError, ValueError:
            return None
        return cls(
            client,
            secret,
            repr((str(runtime), project_version(), project_build_time())),
        )

    def _key(self, key: tuple) -> str:
        """Derive one private slot per prepared variant.

        Returns:
            The Redis key in the current tool and source namespace.
        """
        code = hmac.digest(
            self._secret,
            b"slot\0" + self._namespace + b"\0" + repr(key).encode(),
            "sha256",
        )
        return f"aranami:page:v1:{code.hex()}"

    def _proof(self, key: str, identity: tuple, body: bytes) -> bytes:
        """Bind the page to its slot and committed input generation.

        Returns:
            The proof for the complete stamped payload.
        """
        # Device numbers can vary across mounts of the same shared file.
        return hmac.digest(
            self._secret,
            b"value\0" + key.encode() + repr(identity[1:]).encode() + body,
            "sha256",
        )

    def read(self, key: tuple, identity: tuple) -> tuple[str, float] | None:
        """Reuse an authenticated value for the saved file.

        Returns:
            HTML and seconds until expiry, or none on cache miss.
        """
        if identity == (None,) or time.monotonic() < self._retry_at:
            return None
        slot = self._key(key)
        try:
            value = self._client.getrange(slot, 0, _MAX_VALUE)
        except RedisError:
            self._retry_at = time.monotonic() + _BACKOFF_SECONDS
            return None
        if not isinstance(value, bytes) or not (
            _PROOF_BYTES + _CLOCK.size < len(value) <= _MAX_VALUE
        ):
            return None
        proof, body = value[:_PROOF_BYTES], value[_PROOF_BYTES:]
        if not hmac.compare_digest(proof, self._proof(slot, identity, body)):
            return None
        (expires,) = _CLOCK.unpack_from(body)
        remaining = min(expires - time.time(), _TTL_SECONDS)
        if remaining <= 0:
            return None
        return body[_CLOCK.size :].decode(), remaining

    def put(self, key: tuple, identity: tuple, content: str) -> None:
        """Cache one small prepared variant in its fixed Redis slot."""
        if (
            identity == (None,)
            or len(content) > _MAX_BYTES
            or time.monotonic() < self._retry_at
        ):
            return
        raw = content.encode()
        if not raw or len(raw) > _MAX_BYTES:
            return
        slot = self._key(key)
        body = _CLOCK.pack(time.time() + _TTL_SECONDS) + raw
        try:
            self._client.set(
                slot,
                self._proof(slot, identity, body) + body,
                ex=_TTL_SECONDS,
            )
        except RedisError:
            self._retry_at = time.monotonic() + _BACKOFF_SECONDS

    def close(self) -> None:
        """Release pooled connections when the website stops."""
        self._client.close()
