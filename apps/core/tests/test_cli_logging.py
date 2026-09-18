import logging.config
from unittest import TestCase
from unittest.mock import patch

from config.cli_logging import console_logging


class MaintenanceLoggingTests(TestCase):
    def test_denied_service_log_does_not_block_command_logging(self):
        config = {
            "version": 1, "disable_existing_loggers": False,
            "handlers": {
                "console": {"class": "logging.StreamHandler"},
                "file": {"class": "logging.handlers.RotatingFileHandler", "filename": "denied.log"},
            },
            "loggers": {"maintenance-test": {"handlers": ["console", "file"]}},
            "root": {"handlers": ["file"]},
        }
        result = console_logging(config)
        self.assertIn("file", config["handlers"])
        self.assertEqual(result["loggers"]["maintenance-test"]["handlers"], ["console"])
        self.assertEqual(result["root"]["handlers"], ["maintenance_console"])
        with patch("logging.FileHandler._open", side_effect=PermissionError("Access denied")) as file_open:
            logging.config.dictConfig(result)
        file_open.assert_not_called()
