import json
import re
import unicodedata

import features
import state

BUCKET = "bucket:"
DAY = "day:"
KINDS = ("monitor", "metric", "group")
SHOWN = 60
REASON_CAP = 5
INERT = re.compile(r"[<>@]|://")

OBJECT = state.leaf(lambda value: isinstance(value, dict), "an object")
KIND = state.leaf(lambda value: value in KINDS, "one of " + ", ".join(KINDS))
FILE_SCHEMA = state.leaf(lambda value: state.is_integer(value) and value == 1, "schema 1")

FEATURES_SPEC = {
    "bucket_labels": [state.TEXT],
    "keys": {
        "*": {
            "kind": KIND,
            "source": state.TEXT,
            "title": state.TEXT,
            "link": state.TEXT,
            "values": OBJECT,
            "tracked": state.Nullable({"severity": state.SEVERITY_LEVEL, "when": state.URGENCY_LEVEL}),
            "buckets": state.Omittable([state.PRESENT]),
            "excluded": state.Omittable([state.INTEGER]),
            "days": state.Omittable([{"label": state.TEXT, "value": state.PRESENT}]),
        }
    },
    "auto": {
        "*": {
            "reason": state.TEXT,
            "title": state.TEXT,
            "link": state.TEXT,
            "severity": state.SEVERITY_LEVEL,
            "when": state.URGENCY_LEVEL,
        }
    },
}
BASE_SPEC = {name: spec for name, spec in state.FACTS_SPEC.items() if name != "observations"}
SUMMARY_SPEC = {"new": [{"key": state.TEXT}], "escalated": [{"key": state.TEXT}]}
JUDGMENT_SPEC = {"schema": FILE_SCHEMA, "verdicts": {"*": OBJECT}}
VERDICT_SPEC = {
    "open": state.BOOLEAN,
    "severity": state.SEVERITY_LEVEL,
    "urgency": state.URGENCY_LEVEL,
    "rank": state.Nullable(state.RANK),
    "cites": OBJECT,
}
ANALYSIS_FILE_SPEC = {"schema": FILE_SCHEMA, "items": {"*": OBJECT}}
CLAIM_SPEC = {"tag": state.REASON_TAG, "claim": state.LABEL, "cites": state.Omittable(OBJECT)}
ITEM_SPEC = {
    "risk": state.LABEL,
    "reason": [CLAIM_SPEC],
    "mitigation": state.check_mitigation,
    "action": state.LABEL,
}


def check_features(document):
    state.check(document, FEATURES_SPEC, "")


def check_base(document):
    state.check(document, BASE_SPEC, "")


def check_summary(document):
    state.check(document, SUMMARY_SPEC, "")


def shown(value):
    return json.dumps(value, ensure_ascii=False)[:SHOWN]


def same_value(cited, actual):
    if isinstance(cited, bool) or isinstance(actual, bool):
        return isinstance(cited, bool) and isinstance(actual, bool) and cited == actual
    if state.is_number(cited) and state.is_number(actual):
        return cited == actual or features.rounded(cited) == actual
    return type(cited) is type(actual) and cited == actual


def feature_value(doc, labels, name, path):
    if name.startswith(BUCKET):
        label = name[len(BUCKET) :]
        if "buckets" not in doc or label not in labels:
            raise state.Rejected(f"{path}: the key has no bucket {label}")
        index = labels.index(label)
        if index in doc.get("excluded", []):
            raise state.Rejected(f"{path}: bucket {label} is excluded for the key")
        return doc["buckets"][index]
    if name.startswith(DAY):
        label = name[len(DAY) :]
        day = next((day for day in doc.get("days", []) if day["label"] == label), None)
        if day is None:
            raise state.Rejected(f"{path}: the key has no day {label}")
        return day["value"]
    if name not in doc["values"]:
        raise state.Rejected(f"{path}: the key has no feature {name}")
    return doc["values"][name]


def check_cites(doc, labels, cites, path):
    if cites and doc is None:
        raise state.Rejected(f"{path}: the key is not in the features")
    for name in sorted(cites):
        here = f"{path}.{name}"
        actual = feature_value(doc, labels, name, here)
        if not same_value(cites[name], actual):
            raise state.Rejected(f"{here}: cited {shown(cites[name])}, the features hold {shown(actual)}")


def check_verdict(key, verdict, features_doc, deferred):
    path = f"verdicts.{key}"
    if key in deferred:
        raise state.Rejected(f"{path}: the key is deferred this run")
    if key in features_doc["auto"]:
        raise state.Rejected(f"{path}: the key needs no verdict ({features_doc['auto'][key]['reason']})")
    doc = features_doc["keys"].get(key)
    if doc is None:
        raise state.Rejected(f"{path}: the key is not in the features")
    state.check(verdict, VERDICT_SPEC, path)
    cites = verdict["cites"]
    if not cites:
        raise state.Rejected(f"{path}.cites: a verdict must cite the features it relies on")
    if doc["kind"] == "monitor" and "state" not in cites:
        raise state.Rejected(f"{path}.cites: a monitor verdict must cite state")
    check_cites(doc, features_doc["bucket_labels"], cites, f"{path}.cites")


def check_ranks(verdicts):
    open_keys = [key for key in sorted(verdicts) if verdicts[key]["open"]]
    for key in sorted(verdicts):
        if not verdicts[key]["open"] and verdicts[key]["rank"] is not None:
            raise state.Rejected(f"verdicts.{key}.rank: must be null while open is false")
    holders = {}
    for key in open_keys:
        rank = verdicts[key]["rank"]
        if rank is None:
            raise state.Rejected(f"verdicts.{key}.rank: an open key needs a rank from 1 to {len(open_keys)}")
        if rank > len(open_keys):
            raise state.Rejected(f"verdicts.{key}.rank: {rank} is outside 1 to {len(open_keys)}")
        if rank in holders:
            raise state.Rejected(f"verdicts.{key}.rank: {rank} is also the rank of verdicts.{holders[rank]}.rank")
        holders[rank] = key


def last_value(doc):
    if doc["kind"] == "monitor":
        return doc["values"]["state"]
    return doc["values"].get("value")


def verdict_observation(doc, verdict):
    return {
        "source": doc["source"],
        "over": verdict["open"],
        "value": None if doc["kind"] == "monitor" else doc["values"].get("value"),
        "severity": verdict["severity"],
        "when": verdict["urgency"],
        "title": doc["title"],
        "link": doc["link"],
        "last_value": last_value(doc),
        "rank": verdict["rank"],
    }


def auto_observation(key, auto):
    return {
        "source": state.key_source(key),
        "over": False,
        "value": None,
        "severity": auto["severity"],
        "when": auto["when"],
        "title": auto["title"],
        "link": auto["link"],
        "last_value": auto["reason"],
        "rank": None,
    }


def overridden(features_doc, verdicts):
    keys = features_doc["keys"]
    return sorted(
        key
        for key, verdict in verdicts.items()
        if not verdict["open"] and keys[key]["kind"] == "monitor" and keys[key]["values"]["state"] != features.OK_STATE
    )


def checked_facts(facts):
    try:
        state.check_facts(facts)
    except state.Rejected as error:
        raise state.InputError(f"facts: {error}") from error
    return facts


def judge(features_doc, base, document):
    state.check(document, JUDGMENT_SPEC, "")
    verdicts = document["verdicts"]
    deferred = set(base.get("deferred", []))
    for key in sorted(verdicts):
        check_verdict(key, verdicts[key], features_doc, deferred)
    for key in sorted(set(features_doc["keys"]) - set(features_doc["auto"])):
        if key not in verdicts:
            raise state.Rejected(f"verdicts.{key}: no verdict for an observed key")
    check_ranks(verdicts)
    observations = {key: verdict_observation(features_doc["keys"][key], verdict) for key, verdict in verdicts.items()}
    for key, auto in features_doc["auto"].items():
        observations[key] = auto_observation(key, auto)
    return checked_facts({**base, "observations": observations, "overrides": overridden(features_doc, verdicts)})


def check_claim(claim, doc, labels, path):
    cites = claim.get("cites", {})
    if claim["tag"] == "measured" and not cites:
        raise state.Rejected(f"{path}.cites: a measured claim must cite the features it relies on")
    check_cites(doc, labels, cites, f"{path}.cites")


def has_inert(text):
    return any(INERT.search(form) for form in (text, unicodedata.normalize("NFKC", text)))


def check_inert(item, path):
    texts = {"risk": item["risk"], "action": item["action"]}
    texts.update({f"mitigation[{index}]": text for index, text in enumerate(item["mitigation"])})
    texts.update({f"reason[{index}].claim": claim["claim"] for index, claim in enumerate(item["reason"])})
    for name, text in texts.items():
        if has_inert(text):
            raise state.Rejected(f"{path}.{name}: must not contain <, >, @ or ://")


def check_item(key, item, features_doc):
    path = f"items.{key}"
    state.check(item, ITEM_SPEC, path)
    if len(item["reason"]) > REASON_CAP:
        raise state.Rejected(f"{path}.reason: expected at most {REASON_CAP} claims")
    check_inert(item, path)
    doc = features_doc["keys"].get(key)
    for index, claim in enumerate(item["reason"]):
        check_claim(claim, doc, features_doc["bucket_labels"], f"{path}.reason[{index}]")


def changed_keys(summary):
    return {entry["key"] for name in ("new", "escalated") for entry in summary[name]}


def analysed(observation, item):
    return {
        **observation,
        "risk": item["risk"],
        "reason": [{"tag": claim["tag"], "claim": claim["claim"]} for claim in item["reason"]],
        "mitigation": list(item["mitigation"]),
        "action": item["action"],
    }


def annotate(features_doc, facts, document, summary):
    state.check(document, ANALYSIS_FILE_SPEC, "")
    items = document["items"]
    listed = changed_keys(summary)
    for key in sorted(items):
        if key not in listed:
            raise state.Rejected(f"items.{key}: the key is not new or escalated in the preview summary")
    for key in sorted(listed):
        if key not in items:
            raise state.Rejected(f"items.{key}: no analysis for a key the preview summary lists as new or escalated")
    for key in sorted(items):
        check_item(key, items[key], features_doc)
    observations = dict(facts["observations"])
    for key in sorted(items):
        if key not in observations:
            raise state.InputError(f"facts: observations.{key}: missing, though the preview summary lists the key")
        observations[key] = analysed(observations[key], items[key])
    return checked_facts({**facts, "observations": observations})
