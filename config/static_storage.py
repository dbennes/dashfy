"""Keep compressed downloads without maximum-effort deployment compression."""
import gzip

from whitenoise import compress
from whitenoise.compress import Compressor
from whitenoise.storage import CompressedManifestStaticFilesStorage


class DashboardCompressor(Compressor):
    @staticmethod
    def compress_brotli(data):
        # WhiteNoise's default quality 11 is particularly expensive for GLBs.
        return compress.brotli.compress(data, quality=4)

    @staticmethod
    def compress_gzip(data):
        return gzip.compress(data, compresslevel=6, mtime=0)


class DashboardStaticStorage(CompressedManifestStaticFilesStorage):
    def create_compressor(self, **kwargs):
        return DashboardCompressor(**kwargs)
