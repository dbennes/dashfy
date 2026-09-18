import asyncio
import threading
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from apps.vessels.transport import AISConnection


class AsyncSocket:
    def __init__(self):
        self.calls = []
        self.receives = 0
        self.closed = False

    async def send(self, message):
        self.calls.append((message, threading.current_thread().name))

    async def recv(self):
        self.receives += 1
        if self.receives == 1:
            await asyncio.sleep(30)
        return b'{"MessageType":"PositionReport"}'

    async def close(self):
        self.closed = True


class AISTransportTests(SimpleTestCase):
    def test_receive_timeout_cancels_without_breaking_next_read_and_closes_thread(self):
        socket = AsyncSocket()
        with patch("apps.vessels.transport.connect", new=AsyncMock(return_value=socket)):
            transport = AISConnection("wss://example.invalid", open_timeout=1, close_timeout=1)
            with transport as connection:
                connection.send("subscription")
                with self.assertRaises(TimeoutError):
                    connection.recv(timeout=0.02)
                self.assertEqual(connection.recv(timeout=1), b'{"MessageType":"PositionReport"}')
                self.assertEqual(socket.calls, [("subscription", "ais-websocket")])
            self.assertTrue(socket.closed)
            self.assertFalse(transport.thread.is_alive())
            self.assertTrue(transport.loop.is_closed())

    def test_failed_handshake_releases_event_loop_thread(self):
        with patch("apps.vessels.transport.connect", new=AsyncMock(side_effect=OSError("offline"))):
            transport = AISConnection("wss://example.invalid", open_timeout=1)
            with self.assertRaises(OSError):
                with transport:
                    self.fail("Failed connections must not enter the worker loop")
            self.assertFalse(transport.thread.is_alive())
            self.assertTrue(transport.loop.is_closed())
