"""Console-only logging for maintenance commands; web logging is unchanged."""
from copy import deepcopy


def console_logging(config):
    result = deepcopy(config)
    handlers = result.setdefault("handlers", {})
    file_handlers = {
        name for name, handler in handlers.items()
        if name == "file" or "FileHandler" in handler.get("class", "")
    }
    handlers["maintenance_console"] = {"class": "logging.StreamHandler"}
    for name in file_handlers:
        del handlers[name]
    for logger in [result.get("root", {}), *result.get("loggers", {}).values()]:
        if "handlers" not in logger:
            continue
        original = logger["handlers"]
        logger["handlers"] = [name for name in original if name not in file_handlers]
        if not logger["handlers"] and any(name in file_handlers for name in original):
            logger["handlers"] = ["maintenance_console"]
    return result
