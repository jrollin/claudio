from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import providers
import roles
import state


def adapter_role(adapter):
    return getattr(providers.load(adapter), "ROLE", None)


def accept_any(document):
    return None


def load_zone(name, reason):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
        raise state.InputError(reason) from error


def read_routine(path, routine, place, role_of):
    config = state.load(path, "config", accept_any)
    roles.validate_config(config, routine, place, role_of=role_of)
    chosen = config["routines"][routine]
    sources = {
        name: dict(source, role=role_of(config["providers"][source["provider"]]["adapter"]))
        for name, source in sorted(chosen["sources"].items())
    }
    return config, chosen, sources
