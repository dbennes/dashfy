from concurrent.futures import ThreadPoolExecutor
from datetime import date
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.core.dashboard_cache import cached_dashboard_source
from config.static_storage import DashboardStaticStorage
from whitenoise import compress


@override_settings(DASHFY_SOURCE_CACHE_SECONDS=45)
class DashboardSourceCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_reuses_result_without_sharing_mutable_payload(self):
        loader = Mock(return_value={"rows": [1]})
        source = cached_dashboard_source("test-copy")(loader)
        source()["rows"].append(99)
        self.assertEqual(source(), {"rows": [1]})
        self.assertEqual(loader.call_count, 1)

    def test_different_cutoffs_and_days_do_not_reuse_old_data(self):
        loader = Mock(return_value=[1])
        source = cached_dashboard_source("test-dates")(loader)
        with patch("apps.core.dashboard_cache.timezone.localdate", return_value=date(2026, 9, 24)):
            source(date(2026, 9, 1))
            source(date(2026, 9, 2))
        with patch("apps.core.dashboard_cache.timezone.localdate", return_value=date(2026, 9, 25)):
            source(date(2026, 9, 2))
        self.assertEqual(loader.call_count, 3)

    def test_failed_load_is_retried_and_expiry_is_bounded(self):
        loader = Mock(side_effect=[ValueError("offline"), [2]])
        source = cached_dashboard_source("test-retry")(loader)
        with self.assertRaises(ValueError):
            source()
        with patch.object(cache, "set", wraps=cache.set) as setter:
            self.assertEqual(source(), [2])
            self.assertEqual(setter.call_args.kwargs["timeout"], 45)

    @override_settings(DASHFY_SOURCE_CACHE_SECONDS=0)
    def test_can_disable_cache(self):
        loader = Mock(return_value=[1])
        source = cached_dashboard_source("test-disabled")(loader)
        source()
        source()
        self.assertEqual(loader.call_count, 2)

    def test_concurrent_visitors_share_one_source_load(self):
        entered, release = Event(), Event()
        def load():
            entered.set()
            self.assertTrue(release.wait(5))
            return [1]
        loader = Mock(side_effect=load)
        source = cached_dashboard_source("test-concurrent")(loader)
        with ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(source)
            self.assertTrue(entered.wait(5))
            pending = [pool.submit(source) for _ in range(3)]
            release.set()
            self.assertEqual([first.result(), *[p.result() for p in pending]], [[1]] * 4)
        self.assertEqual(loader.call_count, 1)


class StaticCompressionTests(SimpleTestCase):
    def test_manifest_and_compressed_assets_remain_readable(self):
        with TemporaryDirectory() as directory:
            storage = DashboardStaticStorage(location=directory, base_url="/static/")
            data = b"const dashboard = 'ready';\n" * 1000
            Path(directory, "app.js").write_bytes(data)
            results = list(storage.post_process({"app.js": (storage, "app.js")}))
            self.assertFalse(any(isinstance(result[2], Exception) for result in results))
            hashed = storage.hashed_files["app.js"]
            self.assertTrue(Path(directory, "staticfiles.json").exists())
            for name in ("app.js", hashed):
                self.assertEqual(gzip.decompress(Path(directory, name + ".gz").read_bytes()), data)
                if compress.brotli_installed:
                    self.assertEqual(compress.brotli.decompress(Path(directory, name + ".br").read_bytes()), data)

    def test_gzip_still_works_without_optional_brotli(self):
        with patch.object(compress, "brotli_installed", False):
            compressor = DashboardStaticStorage().create_compressor(quiet=True)
            self.assertFalse(compressor.use_brotli)
            self.assertEqual(gzip.decompress(compressor.compress_gzip(b"test")), b"test")
