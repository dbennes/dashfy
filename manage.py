#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Make sure it's installed and "
            "available on your PYTHONPATH environment variable. "
            "Did you forget to activate a virtual environment?"
        ) from exc
    # Maintenance may run under a different Windows account from the web service.
    # It must not need write access to the service's rotating log file.
    if len(sys.argv) > 1 and sys.argv[1] in {"migrate", "showmigrations", "makemigrations", "collectstatic", "check"}:
        from django.conf import settings
        from config.cli_logging import console_logging
        settings.LOGGING = console_logging(settings.LOGGING)
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
