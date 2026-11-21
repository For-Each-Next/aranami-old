"""Test the shared HTML cache against saved identities and failures."""

from pathlib import Path
from unittest import TestCase, mock

from redis.exceptions import TimeoutError as RedisTimeout

from webservice.page_cache import PageCache
from webservice.redis_page_cache import RedisPageCache

_KEY = ("/quality-analysis/", "en", "current", False, True)
_IDENTITY = (1, 42, 0o100644, 8192, 101, 102)
_SECRET = bytes(range(32))
_HTML = "<p>Prepared article statistics</p>"
_TTL_SECONDS = 45


class TestRedisPageCache(TestCase):
    """Verify the authenticity and lifetime of cached public pages."""

    def setUp(self) -> None:
        """Create a fake connection and a cache for this site."""
        self.client = mock.Mock()
        self.cache = RedisPageCache(self.client, _SECRET, "tool:source")

    def test_share_across_mounts_with_matching_input(self) -> None:
        """Authenticate the prepared generation across file mounts."""
        self.cache.put(_KEY, _IDENTITY, _HTML)
        assert self.client.set.call_args.kwargs["ex"] == _TTL_SECONDS
        self.client.getrange.return_value = self.client.set.call_args.args[1]
        second = RedisPageCache(self.client, _SECRET, "tool:source")
        hit = second.read(_KEY, (9, *_IDENTITY[1:]))
        assert hit is not None
        content, remaining = hit
        assert content == _HTML
        assert 0 < remaining <= _TTL_SECONDS

        assert second.read(_KEY, (*_IDENTITY[:-1], 998)) is None
        assert second.read(("/quality-analysis/", "zh"), _IDENTITY) is None
        self.client.getrange.return_value = (
            self.client.set.call_args.args[1][:-1] + b"x"
        )
        assert second.read(_KEY, _IDENTITY) is None

    def test_expired_and_oversize_values_miss(self) -> None:
        """Ignore old values and bound writes to the shared service."""
        with mock.patch(
            "webservice.redis_page_cache.time.time",
            return_value=1,
        ):
            self.cache.put(_KEY, _IDENTITY, _HTML)
        self.client.getrange.return_value = self.client.set.call_args.args[1]
        assert self.cache.read(_KEY, _IDENTITY) is None
        self.client.set.reset_mock()
        self.cache.put(_KEY, _IDENTITY, "x" * (512 * 1024 + 1))
        self.client.set.assert_not_called()

    def test_redis_timeout_keeps_local_cache_available(self) -> None:
        """Use local pages during a shared-cache outage."""
        self.client.getrange.side_effect = RedisTimeout("test timeout")
        pages = PageCache(self.cache)
        assert pages.get(_KEY, _IDENTITY, shared=True) is None
        pages.put(_KEY, _IDENTITY, _HTML, shared=True)
        self.client.set.assert_not_called()
        assert pages.get(_KEY, _IDENTITY, shared=True) == _HTML
        pages.close()
        self.client.close.assert_called_once()

    @staticmethod
    def test_environment_requires_signing_key() -> None:
        """Leave shared caching disabled without its signing secret."""
        with (
            mock.patch.dict(
                "os.environ",
                {"TOOL_REDIS_URI": "redis://redis:6379"},
                clear=True,
            ),
            mock.patch(
                "webservice.redis_page_cache.Redis.from_url",
            ) as connect,
        ):
            assert RedisPageCache.from_environment(Path("/example")) is None
        connect.assert_not_called()
