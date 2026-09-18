from contextlib import contextmanager
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.vessels.listener import AISStreamListener, WorkerLockLost


_LOCK_ID = 0x4149535354524541


@contextmanager
def exclusive_worker():
    database = connections["default"]
    if database.vendor != "postgresql":
        yield None
        return
    # Keep the advisory lock on a separate connection: closing stale ORM
    # connections during ingestion must not silently release the worker lock.
    lock_connection = database.copy(alias="ais_worker_lock")
    try:
        lock_connection.ensure_connection()
        with lock_connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [_LOCK_ID])
            if not cursor.fetchone()[0]:
                raise CommandError("Another AIS listener already holds the worker lock.")
        yield lock_connection.is_usable
    finally:
        lock_connection.close()


class Command(BaseCommand):
    help = "Collect real AIS positions for active registered vessels. Run one worker separately from the web server."

    def handle(self, *args, **options):
        if not str(getattr(settings, "AISSTREAM_API_KEY", "") or "").strip():
            raise CommandError("Set AISSTREAM_API_KEY in the backend environment before starting the AIS listener.")
        stop = threading.Event()
        previous_handlers = {}
        if threading.current_thread() is threading.main_thread():
            for signal_number in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signal_number] = signal.getsignal(signal_number)
                signal.signal(signal_number, lambda _number, _frame: stop.set())
        try:
            with exclusive_worker() as lease_check:
                self.stdout.write("AIS listener starting. Only active registered MMSIs will be subscribed.")
                AISStreamListener(stop_event=stop, lease_check=lease_check).run()
        except WorkerLockLost as exc:
            raise CommandError("AIS listener lost its worker lock; restart the service.") from exc
        finally:
            for signal_number, handler in previous_handlers.items():
                signal.signal(signal_number, handler)
