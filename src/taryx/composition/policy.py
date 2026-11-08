"""Client policy selection — the only place a client name becomes an import.

TARYX_CLIENT names a package under `taryx.clients`; composition resolves
it once at startup and injects the resulting policy into core services.
Client identity is deployment configuration, never trusted from a
request field.
"""

import importlib
import os
from functools import lru_cache
from types import ModuleType

DEFAULT_CLIENT = "aurora_energy"


@lru_cache(maxsize=1)
def selected_client_id() -> str:
    return os.environ.get("TARYX_CLIENT", DEFAULT_CLIENT)


@lru_cache(maxsize=1)
def policy() -> ModuleType:
    client = selected_client_id()
    try:
        return importlib.import_module(f"taryx.clients.{client}.policy")
    except ImportError as exc:
        raise RuntimeError(
            f"unknown TARYX_CLIENT {client!r}: no policy under taryx.clients"
        ) from exc
