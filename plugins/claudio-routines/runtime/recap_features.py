import decimal
import re

import evaluate
import features
import recap_state
import recap_window
import roles
import state
import tribe_features
from config import adapter_role
from providers._errors import PAGE_CAP_PARTIAL

WAITING_ON_YOU = "waiting on you"
TEAM_ASK = "team ask"
YOURE_WAITING_ON = "you're waiting on"
PROMISE = "promise"
ALREADY_HANDLED = "already handled"
ANNOUNCEMENT = "announcement"
NOISE = "noise"
KIND_DEFINITIONS = {
    WAITING_ON_YOU: "someone asked the owner something, or wrote to the owner, and the owner has not answered",
    TEAM_ASK: "an ask to a group the owner belongs to, still without an answer from anyone",
    YOURE_WAITING_ON: "the owner wrote last and waits for an answer or an action",
    PROMISE: "the owner committed to do something, with its due time when the message names one",
    ALREADY_HANDLED: "the owner answered, or a stored waiting unit that is now settled",
    ANNOUNCEMENT: "a message of an announcement channel on a topic the owner keeps",
    NOISE: "nothing for the owner to do or to know",
}
CONVERSATION_NAMES = {"DM": "dm", "group DM": "group_dm"}
SEARCH_PREFIX = "search:"
SEARCH_CUT = re.compile(re.escape(PAGE_CAP_PARTIAL) + r": ([0-9]+) page\(s\) read")
MESSAGE_FIELDS = ("user", "name", "bot", "ts", "root_ts", "mentions", "group_mentions", "text")


class Settings:
    def __init__(self, routine):
        self.owner = routine["owner"]
        self.groups = [{"id": item["id"], "label": item["label"], "lands_in": item["lands_in"]} for item in routine["groups"]]
        announcement, exclude = routine["announcement"], routine["exclude"]
        self.announcement_channels = announcement.get("channels", [])
        self.topics = announcement.get("topics", [])
        self.exclude_authors = exclude.get("authors", [])
        self.exclude_channels = exclude.get("channels", [])
        self.keep_bots = exclude.get("keep_bots", [])
        self.rules = routine["rules"]
        self.thread_reads = routine.get("thread_reads", "full")


def kept(message, settings):
    user = message["user"]
    return user not in settings.exclude_authors and not (message["bot"] and user not in settings.keep_bots)


def merged(before, message):
    joined = {
        **before,
        "bot": before["bot"] or message["bot"],
        "name": before["name"] or message["name"],
        "root_ts": before["root_ts"] or message["root_ts"],
        "mentions": sorted({*before["mentions"], *message["mentions"]}),
        "group_mentions": sorted({*before["group_mentions"], *message["group_mentions"]}),
    }
    if "owner_reacted" in before or "owner_reacted" in message:
        joined["owner_reacted"] = before.get("owner_reacted", False) or message.get("owner_reacted", False)
    return joined


def unit_of(units, key, record, kind):
    return units.setdefault(key, {"kind": kind, "channel": record["channel"], "name": record["name"], "participants": {}, "messages": {}})


def add_record(units, record, settings):
    conversation = CONVERSATION_NAMES.get(record["name"])
    for message in record["messages"]:
        if not kept(message, settings):
            continue
        key = recap_state.dm_key(record["channel"]) if conversation else recap_state.thread_key(record["channel"], message["root_ts"] or message["ts"])
        unit = unit_of(units, key, record, conversation)
        stamp = decimal.Decimal(message["ts"])
        copy = {field: message[field] for field in MESSAGE_FIELDS}
        copy.update({"owner_reacted": message["owner_reacted"]} if "owner_reacted" in message else {})
        unit["messages"][stamp] = merged(unit["messages"][stamp], copy) if stamp in unit["messages"] else copy
        for person in record["participants"]:
            unit["participants"].setdefault(person["id"], person["name"])


def read_units(sources, collections, settings):
    units = {}
    for name, source in sorted(sources.items()):
        collection = collections[name]
        if source["role"] != "chat" or not collection["read"]:
            continue
        for record in collection["records"].get("units", []):
            if record["channel"] not in settings.exclude_channels:
                add_record(units, record, settings)
    return units


def is_ask_after(message, answered, owner):
    return message["user"] != owner and (answered is None or decimal.Decimal(message["ts"]) > answered)


def answered_at(messages, owner):
    stamps = [decimal.Decimal(item["ts"]) for item in messages if item["user"] == owner or item.get("owner_reacted") is True]
    return max(stamps, default=None)


def later(*stamps):
    return max((stamp for stamp in stamps if stamp is not None), default=None)


def stored_owner_ts(previous):
    stamp = None if previous is None else previous.get("owner_last_ts")
    return None if stamp is None else decimal.Decimal(stamp)


def group_facts(messages, settings):
    found = []
    for group in settings.groups:
        asks = [item for item in messages if item["user"] != settings.owner and group["id"] in item["group_mentions"]]
        if asks:
            first = asks[0]
            replied = any(decimal.Decimal(item["ts"]) > decimal.Decimal(first["ts"]) and item["user"] != first["user"] for item in messages)
            found.append({**group, "answered": replied})
    return found


def facts_of(channel, messages, settings, previous, zone, window, merge_owner=False):
    owner = settings.owner
    read_at = answered_at(messages, owner)
    stored_at = stored_owner_ts(previous) if merge_owner else None
    answered = later(read_at, stored_at)
    asks = [item for item in messages if is_ask_after(item, answered, owner)]
    unanswered = asks[0]["ts"] if asks else None
    return {
        "last_author_is_owner": messages[-1]["user"] == owner,
        "unanswered_from": unanswered,
        "groups": group_facts(messages, settings),
        "announcement_channel": channel in settings.announcement_channels,
        "direct_mention": any(item["user"] != owner and owner in item["mentions"] for item in messages),
        "owner_answered": unanswered is None and any(item["user"] != owner for item in messages),
        "owner_took_part": stored_at is not None or any(item["user"] == owner for item in messages),
        "owner_last_ts": None if read_at is None else str(read_at),
        "age_working_days": None if unanswered is None else recap_window.working_days_between(int(decimal.Decimal(unanswered)), window["to_ts"], zone),
        "previous": previous,
    }


def thread_kind(facts):
    if facts["direct_mention"]:
        return "mention"
    return "group" if facts["groups"] else "thread"


def allowed_kinds(kind, facts):
    asked = facts["unanswered_from"] is not None
    groups, previous = facts["groups"], facts["previous"]
    to_owner = kind in recap_state.DM_KINDS or facts["direct_mention"] or facts["owner_took_part"] or any(item["lands_in"] == "waiting" for item in groups)
    team = any(item["lands_in"] == "good_to_know" and not item["answered"] for item in groups)
    last_is_owner = facts["last_author_is_owner"]
    held = previous is not None and previous["status"] in recap_state.HELD_STATUSES
    allowed = {
        WAITING_ON_YOU: asked and to_owner,
        TEAM_ASK: asked and team,
        YOURE_WAITING_ON: last_is_owner,
        PROMISE: last_is_owner,
        ALREADY_HANDLED: facts["owner_answered"] or held,
        ANNOUNCEMENT: facts["announcement_channel"],
        NOISE: True,
    }
    return [name for name, ok in allowed.items() if ok]


def unit_documents(units, settings, stored, zone, window):
    documents, people = {}, {}
    for key in sorted(units):
        unit = units[key]
        messages = [unit["messages"][stamp] for stamp in sorted(unit["messages"])]
        merge_owner = settings.thread_reads == "since" and recap_state.THREAD_KEY.fullmatch(key) is not None
        facts = facts_of(unit["channel"], messages, settings, stored["units"].get(key), zone, window, merge_owner)
        kind = unit["kind"] or thread_kind(facts)
        documents[key] = {"kind": kind, "channel": unit["channel"], "name": unit["name"], "messages": messages, "facts": dict(sorted(facts.items())), "allowed": allowed_kinds(kind, facts)}
        people[key] = {"channel": unit["channel"], "name": unit["name"], "participants": listed(unit["participants"]), "authors": listed({item["user"]: item["name"] for item in messages})}
    return documents, people


def listed(names):
    return [{"id": who, "name": names[who]} for who in sorted(names)]


def blind_spot_gap(key, entry):
    cut = SEARCH_CUT.fullmatch(entry["reason"]) if key.startswith(SEARCH_PREFIX) else None
    if cut is not None:
        return f"search {key[len(SEARCH_PREFIX):]} cut: {cut.group(1)} page(s) read"
    return features.label(f"{key}: {entry['reason']}")


def blind_spots(sources, collections):
    found = {}
    for name in sorted(sources):
        collection = collections[name]
        if not collection["read"]:
            found.setdefault(name, features.label(collection["reason"]))
            continue
        for key, entry in sorted(collection["entries"].items()):
            if entry["status"] == "failed":
                found.setdefault(key, blind_spot_gap(key, entry))
    return [{"key": key, "gap": found[key]} for key in sorted(found)]


def compute(routine, settings, sources, collections, stored, window, zone):
    units, people = unit_documents(read_units(sources, collections, settings), settings, stored, zone, window)
    spots = blind_spots(sources, collections)
    features_doc = {"owner": settings.owner, "window": window, "units": units, "blind_spots": spots}
    base = {"sources": tribe_features.source_rows(sources, collections, window), "units": people, "blind_spots": spots, "models": routine.get("models", {})}
    rules = {"rules": settings.rules, "kinds": KIND_DEFINITIONS, "announcement_topics": settings.topics}
    return features_doc, base, rules


def load_inputs(args, role_of):
    config, routine, sources = evaluate.load_config(args.config, args.routine, args.place, role_of)
    if routine.get("engine") != roles.RECAP_ENGINE:
        raise state.InputError(f"config: routine {args.routine} is not a recap routine")
    settings = Settings(routine)
    zone = evaluate.config_zone(config)
    stored = recap_state.load(args.state)
    window = state.load(args.window, "window", recap_window.check_window)
    collections = {name: evaluate.read_collection(args.collections, name, source, args.place, window) for name, source in sources.items()}
    return routine, settings, sources, collections, stored, window, zone


def run_features(args, role_of=adapter_role):
    features_doc, base, rules = compute(*load_inputs(args, role_of))
    state.write_all(
        [
            (args.out, features.compact_dump(features_doc)),
            (args.base_out, state.dump(base)),
            (args.rules_out, features.compact_dump(rules)),
        ]
    )
    return 0
