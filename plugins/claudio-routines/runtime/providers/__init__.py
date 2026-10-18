import importlib
import pkgutil
import re

ADAPTER_NAME = re.compile(r"[a-z][a-z0-9]*")


def load(name):
    if not isinstance(name, str) or not ADAPTER_NAME.fullmatch(name):
        raise ValueError(f"provider adapter {name!r}: name must match {ADAPTER_NAME.pattern}")
    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError as exc:
        raise ValueError(f"provider adapter {name}: cannot be imported ({exc})") from None


def names():
    return sorted(module.name for module in pkgutil.iter_modules(__path__) if ADAPTER_NAME.fullmatch(module.name))
