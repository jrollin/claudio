import json
import os
import re

from roles import DEFAULT_ENGINE, ENGINES, ENV_VAR, PLACES, TRANSPORTS, ConfigError, transports_of

SLUG = re.compile(r"[a-z0-9-]+")
ROUTINE_FILE = re.compile(rf"({SLUG.pattern})\.json")
KEY_PATH = re.compile(r"(?<![A-Za-z0-9_.-])routines\.([a-z0-9-]+)\.")
SHARED_KEYS = ("timezone", "runtime", "places", "providers")
ROUTINES_DIR = "config/routines"
SECRET_NAMES = ("password", "passwd", "secret", "token", "api_key", "apikey", "app_key", "private_key")
NAME_MAPS = ("routines", "providers", "sources")
CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
TOKEN = re.compile(
    "|".join(
        (
            r"ghp_[A-Za-z0-9]{36}",
            r"gh[ousr]_[A-Za-z0-9]{36}",
            r"github_pat_[A-Za-z0-9_]{22,}",
            r"xox[abprs]-[A-Za-z0-9-]{10,}",
            r"(?:AKIA|ASIA)[0-9A-Z]{16}",
            r"AIza[0-9A-Za-z_-]{35}",
            r"figd_[A-Za-z0-9_-]{30,}",
            r"sk-ant-[A-Za-z0-9_-]{20,}",
            r"sk-proj-[A-Za-z0-9_-]{20,}",
            r"glpat-[A-Za-z0-9_-]{20}",
            r"npm_[A-Za-z0-9]{36}",
            r"ATATT[A-Za-z0-9_=-]{20,}",
            r"eyJ[A-Za-z0-9_-]{7,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
            r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----",
        )
    )
)


def _file_name(slug):
    return f"{ROUTINES_DIR}/{slug}.json"


def _routines_folder(directory):
    return os.path.join(directory, *ROUTINES_DIR.split("/"))


def has_file(directory, slug):
    return SLUG.fullmatch(slug) is not None and os.path.lexists(
        os.path.join(_routines_folder(directory), slug + ".json")
    )


def routine_file(slug):
    return _file_name(slug) if SLUG.fullmatch(slug) is not None else None


def _where(slug, in_file):
    return f"{_file_name(slug)}: " if in_file else f"config.json: routines.{slug}."


def label(directory, slug):
    return _where(slug, has_file(directory, slug))


def locate(message, directory):
    def rewrite(match):
        slug = match.group(1)
        return f"{_file_name(slug)}: " if has_file(directory, slug) else match.group(0)

    return KEY_PATH.sub(rewrite, message)


def load(path, routine=None):
    directory = os.path.dirname(path)
    config = _read_object(path, os.path.basename(path))
    _reject_secrets(config, "config.json: ")
    inline = config.get("routines", {})
    if not isinstance(inline, dict):
        raise ConfigError("config.json: routines: must be a mapping")
    files = _read_routine_files(directory, routine)
    for slug in sorted(files):
        if slug in inline:
            raise ConfigError(f"routine {slug} is defined twice: config.json: routines.{slug} and {_file_name(slug)}")
    providers = config.get("providers")
    providers = providers if isinstance(providers, dict) else {}
    _check_provider_transports(providers)
    routines = {**inline, **files}
    for slug in _resolved_slugs(routines, routine):
        routines[slug] = _resolve_routine(routines[slug], _where(slug, slug in files), providers)
    if routine is None:
        _check_ids(routines, files)
    return {**config, "routines": routines}


def _resolved_slugs(routines, routine):
    if routine is None:
        return sorted(routines)
    return [routine] if routine in routines else []


def _read_object(path, name):
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise ConfigError(f"{name}: cannot read the file: {error.strerror}") from error
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(f"{name}: must be UTF-8") from error
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ConfigError(f"{name}: invalid JSON: {error.msg} at line {error.lineno} column {error.colno}") from error
    if not isinstance(document, dict):
        raise ConfigError(f"{name}: must be a JSON object")
    return document


def _read_routine_files(directory, only):
    folder = _routines_folder(directory)
    if only is None:
        slugs = _listed_slugs(folder)
    else:
        slugs = [only] if has_file(directory, only) else []
    files = {}
    for slug in slugs:
        document = _read_object(os.path.join(folder, slug + ".json"), _file_name(slug))
        _reject_secrets(document, f"{_file_name(slug)}: ")
        for key in SHARED_KEYS:
            if key in document:
                raise ConfigError(f"{_file_name(slug)}: {key}: belongs in config.json only")
        files[slug] = document
    return files


def _names_secret(key):
    words = CAMEL_BOUNDARY.sub(r"\1_\2", key).replace("-", "_").lower()
    return any(words == name or words.endswith("_" + name) for name in SECRET_NAMES)


def _reject_secrets(node, where, path="", secret=False):
    if isinstance(node, dict):
        for key in sorted(node):
            if TOKEN.search(key):
                raise ConfigError(f"{where}{path or 'top level'}: token: a key looks like a secret, keep it in an environment variable")
            child = f"{path}.{key}" if path else key
            names_a_secret = _names_secret(key) and path.rpartition(".")[2] not in NAME_MAPS
            _reject_secrets(node[key], where, child, secret or names_a_secret)
    elif secret and not (isinstance(node, str) and ENV_VAR.fullmatch(node)):
        raise ConfigError(f"{where}{path}: secret-key: holds a secret, name an environment variable instead")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _reject_secrets(item, where, f"{path}[{index}]")
    elif isinstance(node, str) and TOKEN.search(node):
        raise ConfigError(f"{where}{path}: token: looks like a secret, keep it in an environment variable")


def _listed_slugs(folder):
    try:
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return []
    except OSError as error:
        raise ConfigError(f"{ROUTINES_DIR}: cannot list the directory: {error.strerror}") from error
    slugs = []
    for name in names:
        if not name.endswith(".json"):
            continue
        match = ROUTINE_FILE.fullmatch(name)
        if match is None:
            raise ConfigError(f"{ROUTINES_DIR}/{name}: the file name must match ^[a-z0-9-]+\\.json$")
        slugs.append(match.group(1))
    return slugs


def _check_provider_transports(providers):
    for name in sorted(providers):
        provider = providers[name]
        if isinstance(provider, dict) and "transport" in provider:
            _check_places(provider["transport"], "config.json: ", f"providers.{name}.transport")


def _check_places(transport, where, path):
    if not isinstance(transport, dict):
        raise ConfigError(f"{where}{path}: must be a mapping")
    for place in sorted(transport):
        if place not in PLACES:
            raise ConfigError(f"{where}{path}.{place}: the place must be one of " + ", ".join(PLACES))
        _check_transports(transport[place], f"{where}{path}.{place}")


def _check_transports(value, path):
    if not isinstance(value, list):
        if value not in TRANSPORTS:
            raise ConfigError(f"{path}: must be one of " + ", ".join(TRANSPORTS))
        return
    if not value:
        raise ConfigError(f"{path}: must not be an empty list")
    for index, item in enumerate(value):
        if item not in TRANSPORTS:
            raise ConfigError(f"{path}[{index}]: must be one of " + ", ".join(TRANSPORTS))
    for index, item in enumerate(value):
        if item in value[:index]:
            raise ConfigError(f"{path}: lists {item} more than once")


def _resolve_routine(routine, where, providers):
    if isinstance(routine, dict) and routine.get("engine", DEFAULT_ENGINE) not in ENGINES:
        raise ConfigError(f"{where}engine: must be one of " + ", ".join(ENGINES))
    if not isinstance(routine, dict) or not isinstance(routine.get("sources"), dict):
        return routine
    sources = {
        name: _resolve_source(source, f"{where}sources.{name}.transport", providers)
        for name, source in sorted(routine["sources"].items())
    }
    return {**routine, "sources": sources}


def _resolve_source(source, path, providers):
    if not isinstance(source, dict):
        return source
    own = source.get("transport", {})
    if not isinstance(own, dict):
        return source
    _check_places(own, "", path)
    provider = _provider_of(source, providers)
    default = provider.get("transport", {}) if provider is not None else {}
    chosen = {place: _listed(own.get(place, default.get(place))) for place in PLACES}
    unresolved = [place for place in PLACES if chosen[place] is None]
    if unresolved and provider is None:
        return source
    if unresolved:
        raise ConfigError(f"{path}.{unresolved[0]}: not set on the source, and its provider sets no default")
    return {**source, "transport": chosen}


def _listed(value):
    return None if value is None else list(transports_of(value))


def _provider_of(source, providers):
    name = source.get("provider")
    provider = providers.get(name) if isinstance(name, str) else None
    return provider if isinstance(provider, dict) else None


def _check_ids(routines, files):
    seen = {}
    for slug in sorted(routines):
        routine = routines[slug]
        value = routine.get("id") if isinstance(routine, dict) else None
        if not isinstance(value, str):
            continue
        if value in seen:
            first = _where(seen[value], seen[value] in files) + "id"
            second = _where(slug, slug in files) + "id"
            raise ConfigError(f"two routines have the same id: {first} and {second}")
        seen[value] = slug
