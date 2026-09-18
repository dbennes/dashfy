"""Run TLS I/O on one event loop while the collector uses synchronous Django ORM.

Concurrent blocking SSL reads/writes can hang on Windows. This adapter keeps
all WebSocket I/O asynchronous and preserves bounded synchronous worker calls.
"""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import threading

from websockets.asyncio.client import connect


class AISConnection:
    def __init__(self, uri, **options):
        self.uri = uri
        self.options = options
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="ais-websocket", daemon=True)
        self.socket = None

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def _call(self, coroutine, timeout):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            future.cancel()
            raise TimeoutError("AIS transport operation timed out") from None

    async def _open(self):
        self.socket = await connect(self.uri, **self.options)

    def __enter__(self):
        self.thread.start()
        try:
            self._call(self._open(), float(self.options.get("open_timeout", 10)) + 2)
        except BaseException:
            self._stop()
            raise
        return self

    def send(self, message):
        return self._call(self.socket.send(message), 10)

    def recv(self, timeout=None):
        # Cancelling async recv is safe: the next call receives the next message.
        return self._call(self.socket.recv(), timeout)

    def _stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self.socket is not None:
                self._call(self.socket.close(), float(self.options.get("close_timeout", 5)) + 2)
        finally:
            self._stop()
