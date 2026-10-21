import copy
import re
import unicodedata

import judgment
import state
import tribe_state

CONFIDENCES = tribe_state.CONFIDENCES
STATUSES = tribe_state.STATUSES
VERDICTS = ("open", "under")
GROUPS = tribe_state.CHECK_GROUPS
NAME_CAP = tribe_state.KEY_CAP
WARNING_FIELDS = (
    "title", "topic", "severity", "when", "runway", "status", "confidence", "risk", "impact", "mitigation", "metric", "verdict",
)
CHECK_FIELDS = ("text", "topic", "group")
DECISION_FIELDS = ("decision", "deadline", "options", "topic")
COVERAGE_FIELDS = ("source", "text")
RECORD_CITE = tribe_state.RECORD_CITE
FEATURE_CITE = {**tribe_state.FEATURE_CITE, "value": state.PRESENT}


def named(value):
    return state.clean_text(str(value), NAME_CAP)


def exact(spec):
    def check_exact(value, path):
        state.check(value, spec, path)
        for name in sorted(value):
            if name not in spec:
                raise state.Rejected(f"{state.join(path, named(name))}: unknown field")

    return check_exact


def keyed(check_name, spec):
    def check_keyed(value, path):
        if not isinstance(value, dict):
            raise state.Rejected(f"expected an object at {path}")
        for name in sorted(value):
            check_name(name, f"{path}.{named(name)}")
        state.check(value, {"*": spec}, path)

    return check_keyed


def kebab_name(name, path):
    if not tribe_state.is_key(name):
        raise state.Rejected(
            f"{path}: the key must be kebab-case, lowercase letters and digits joined by hyphens, at most {tribe_state.KEY_CAP} characters"
        )


def text_leaf(authors):
    ids = [re.escape(author) for author in authors if isinstance(author, str) and author]
    held = re.compile(r"(?<!\w)(?:" + "|".join(ids) + r")(?!\w)") if ids else None

    def check_text(value, path):
        state.LABEL(value, path)
        if not value.strip():
            raise state.Rejected(f"{path}: must not be empty")
        normalized = unicodedata.normalize("NFKC", value)
        state.LABEL(normalized, path)
        if held and any(held.search(form) for form in (value, normalized)):
            raise state.Rejected(f"{path}: must not hold a chat author id")
        if judgment.INERT.search(normalized):
            raise state.Rejected(f"{path}: must not contain <, >, @ or ://")

    return check_text


def check_cite_shape(value, path):
    if not isinstance(value, dict) or ("link" in value) == ("feature" in value):
        raise state.Rejected(f"expected a record cite with source and link, or a feature cite with feature, name and value, at {path}")
    if "feature" not in value:
        state.check(value, exact(RECORD_CITE), path)
    else:
        state.check(value, exact(FEATURE_CITE if "value" in value else tribe_state.FEATURE_CITE), path)


def check_cites(value, path):
    if isinstance(value, list) and not value:
        raise state.Rejected(f"{path}: expected at least 1 cite")
    state.check(value, [check_cite_shape], path)


def mitigation_leaf(label):
    def check_mitigation(value, path):
        if not isinstance(value, list) or not 1 <= len(value) <= state.MITIGATION_CAP:
            raise state.Rejected(f"expected a list of 1 to {state.MITIGATION_CAP} labels at {path}")
        state.check(value, [label], path)

    return check_mitigation


def capped_list(cap, noun, entry):
    def check_list(value, path):
        if isinstance(value, list) and len(value) > cap:
            raise state.Rejected(f"{path}: expected at most {cap} {noun}, got {len(value)}")
        state.check(value, [entry], path)

    return check_list


def source_leaf(label):
    def check_source(value, path):
        label(value, path)
        if any(len(form) > tribe_state.COVERAGE_SOURCE_CAP for form in (value, unicodedata.normalize("NFKC", value))):
            raise state.Rejected(f"{path}: must be at most {tribe_state.COVERAGE_SOURCE_CAP} characters")

    return check_source


def judgment_spec(features_doc):
    label = text_leaf(features_doc["authors"])
    pack = features_doc["pack"]
    warning = {
        "title": label,
        "topic": label,
        "severity": state.SEVERITY_LEVEL,
        "when": state.URGENCY_LEVEL,
        "runway": label,
        "status": tribe_state.one_of(STATUSES),
        "confidence": tribe_state.one_of(CONFIDENCES),
        "risk": label,
        "impact": label,
        "mitigation": mitigation_leaf(label),
        "metric": state.Nullable(state.leaf(lambda value: value in pack, "an entry of the query pack")),
        "verdict": tribe_state.one_of(VERDICTS),
        "evidence": [exact({"claim": label, "cites": check_cites})],
        "replaces": state.Omittable(state.Nullable(state.TEXT)),
    }
    return exact(
        {
            "warnings": keyed(kebab_name, exact(warning)),
            "checks": keyed(kebab_name, exact({"text": label, "topic": label, "group": tribe_state.one_of(GROUPS)})),
            "decisions": capped_list(tribe_state.DECISION_CAP, "decisions", exact(dict.fromkeys(DECISION_FIELDS, label))),
            "details": keyed(label, [exact({"text": label, "cites": check_cites})]),
            "corrections": [exact({"was": label, "now": label, "cites": check_cites})],
            "highlights": [exact({"text": label, "cites": check_cites})],
            "coverage_notes": state.Omittable(
                capped_list(tribe_state.COVERAGE_NOTE_CAP, "notes", exact({"source": source_leaf(label), "text": label}))
            ),
        }
    )


def record_pairs(keys):
    return {(doc["source"], doc["link"]) for doc in keys.values() if doc["link"]}


def stored_pairs(stored_warning):
    return {(cite["source"], cite["link"]) for cite in stored_warning.get("cites", []) if "link" in cite}


def stored_features(stored_warning):
    return {(cite["feature"], cite["name"]) for cite in stored_warning.get("cites", []) if "feature" in cite}


def check_record_cite(cite, path, pairs):
    if (cite["source"], cite["link"]) in pairs:
        return
    if any(cite["link"] == link for _, link in pairs):
        raise state.Rejected(f"{path}.source: {named(cite['source'])} is not a source of that link")
    raise state.Rejected(f"{path}.link: matches no link of the features and no cite stored with the warning")


def feature_value(cite, keys, path):
    doc = keys.get(cite["feature"])
    if doc is None:
        raise state.Rejected(f"{path}.feature: {named(cite['feature'])} is not in the features")
    if cite["name"] not in doc["values"]:
        raise state.Rejected(f"{path}.name: {named(cite['feature'])} has no value {named(cite['name'])}")
    return doc["values"][cite["name"]]


def check_feature_cite(cite, path, keys):
    actual = feature_value(cite, keys, path)
    if not judgment.same_value(cite["value"], actual):
        raise state.Rejected(f"{path}.value: cited {judgment.shown(cite['value'])}, the features hold {judgment.shown(actual)}")


def check_stored_feature_cite(cite, path, keys, stored):
    if (cite["feature"], cite["name"]) not in stored:
        raise state.Rejected(f"{path}.value: missing, only a cite stored with the warning omits its value")
    if cite["name"] in keys.get(cite["feature"], {}).get("values", {}):
        raise state.Rejected(f"{path}.value: missing, the features hold {named(cite['feature'])} {named(cite['name'])} this run")


def check_cite_list(cites, path, keys, pairs, stored=frozenset()):
    for index, cite in enumerate(cites):
        if "feature" in cite and "value" not in cite:
            check_stored_feature_cite(cite, f"{path}[{index}]", keys, stored)
        elif "feature" in cite:
            check_feature_cite(cite, f"{path}[{index}]", keys)
        else:
            check_record_cite(cite, f"{path}[{index}]", pairs)


def check_replaces(key, warning, previous, deferred, warnings, replaced):
    path = f"warnings.{key}.replaces"
    target = warning["replaces"]
    if key in previous["warnings"]:
        raise state.Rejected(f"{path}: a stored warning replaces no other")
    if target not in previous["warnings"]:
        raise state.Rejected(f"{path}: {named(target)} is not a stored warning")
    if target in deferred:
        raise state.Rejected(f"{path}: {target} is deferred this run and is held, not replaced")
    if target in warnings:
        raise state.Rejected(f"{path}: {target} is also judged in this run")
    if target in replaced:
        raise state.Rejected(f"{path}: {target} is already replaced by warnings.{replaced[target]}")
    replaced[target] = key


def folded(title):
    return " ".join(unicodedata.normalize("NFKC", title).split()).casefold()


def check_title(key, warning, previous):
    path = f"warnings.{key}.title"
    for old_key, old in sorted(previous["warnings"].items()):
        if old_key != key and folded(warning["title"]) == folded(old["title"]) and warning.get("replaces") != old_key:
            raise state.Rejected(f"{path}: matches the title of the stored warning {old_key}; name it in replaces or retitle")
    if key in previous["warnings"]:
        return
    for old_key, old_title in sorted(previous["retired"].items()):
        if folded(warning["title"]) == folded(old_title):
            raise state.Rejected(f"{path}: matches the title of the retired key {old_key}")


def check_warning_key(key, previous, checks):
    path = f"warnings.{key}"
    if key in previous["retired"]:
        raise state.Rejected(f"{path}: the key is retired and never reused")
    if key in previous["checks"]:
        raise state.Rejected(f"{path}: the key belongs to a stored check")
    if key in checks:
        raise state.Rejected(f"{path}: the key is also a check key in this run")


def evidence_cites(warning):
    cites = []
    for item in warning["evidence"]:
        cites.extend(item["cites"])
    return cites


def check_evidence(key, warning, keys, pairs, previous):
    path = f"warnings.{key}"
    stored_warning = previous["warnings"].get(key, {})
    known, stored = pairs | stored_pairs(stored_warning), stored_features(stored_warning)
    for index, item in enumerate(warning["evidence"]):
        check_cite_list(item["cites"], f"{path}.evidence[{index}].cites", keys, known, stored)
    cites = evidence_cites(warning)
    if warning["confidence"] == "measured" and not any("feature" in cite for cite in cites):
        raise state.Rejected(f"{path}.evidence: a measured warning must cite a feature value")
    if warning["confidence"] == "reported" and not any("link" in cite for cite in cites):
        raise state.Rejected(f"{path}.evidence: a reported warning must cite a record")


def check_warnings(features_doc, document, pairs):
    warnings = document["warnings"]
    previous = features_doc["previous"]
    deferred = set(features_doc["deferred"])
    replaced = {}
    titles = {}
    for key in sorted(warnings):
        warning = warnings[key]
        check_warning_key(key, previous, document["checks"])
        if warning.get("replaces") is not None:
            check_replaces(key, warning, previous, deferred, warnings, replaced)
        check_title(key, warning, previous)
        if folded(warning["title"]) in titles:
            raise state.Rejected(f"warnings.{key}.title: same title as warnings.{titles[folded(warning['title'])]}")
        titles[folded(warning["title"])] = key
    for key in sorted(previous["warnings"]):
        if key not in warnings and key not in deferred and key not in replaced:
            raise state.Rejected(f"warnings.{key}: a stored warning needs a judgment, unless it is deferred or replaced")
    for key in sorted(warnings):
        check_evidence(key, warnings[key], features_doc["keys"], pairs, previous)


def check_checks(features_doc, checks):
    previous = features_doc["previous"]
    for key in sorted(checks):
        if key in previous["retired"]:
            raise state.Rejected(f"checks.{key}: the key is retired and never reused")
        if key in previous["warnings"]:
            raise state.Rejected(f"checks.{key}: the key belongs to a stored warning")


def all_stored_pairs(previous):
    pairs = set()
    for stored_warning in previous["warnings"].values():
        pairs |= stored_pairs(stored_warning)
    return pairs


def check_coverage_notes(notes):
    seen = {}
    for index, note in enumerate(notes):
        name = folded(note["source"])
        if name in seen:
            raise state.Rejected(f"coverage_notes[{index}].source: same source as coverage_notes[{seen[name]}]")
        seen[name] = index


def check_cited_sections(document, keys, pairs):
    for topic in sorted(document["details"]):
        for index, entry in enumerate(document["details"][topic]):
            check_cite_list(entry["cites"], f"details.{named(topic)}[{index}].cites", keys, pairs)
    for name in ("corrections", "highlights"):
        for index, entry in enumerate(document[name]):
            check_cite_list(entry["cites"], f"{name}[{index}].cites", keys, pairs)


def check(features_doc, document):
    state.check(document, judgment_spec(features_doc), "")
    pairs = record_pairs(features_doc["keys"])
    check_warnings(features_doc, document, pairs)
    check_checks(features_doc, document["checks"])
    check_coverage_notes(document.get("coverage_notes", []))
    check_cited_sections(document, features_doc["keys"], pairs | all_stored_pairs(features_doc["previous"]))


def stored_cites(cites):
    return [
        {"feature": cite["feature"], "name": cite["name"]} if "feature" in cite else {"source": cite["source"], "link": cite["link"]}
        for cite in cites
    ]


def picked(entry, fields):
    return {name: copy.deepcopy(entry[name]) for name in fields}


def with_stored_cites(entry, fields):
    return {**picked(entry, fields), "cites": stored_cites(entry["cites"])}


def projected_warning(warning):
    evidence = [with_stored_cites(item, ("claim",)) for item in warning["evidence"]]
    cites = []
    for item in evidence:
        for cite in item["cites"]:
            if cite not in cites:
                cites.append(cite)
    projected = {**picked(warning, WARNING_FIELDS), "evidence": evidence, "cites": cites}
    if warning.get("replaces") is not None:
        projected["replaces"] = warning["replaces"]
    return projected


def checked_judgment(features_doc, document):
    check(features_doc, document)
    return {
        "warnings": {key: projected_warning(warning) for key, warning in document["warnings"].items()},
        "checks": {key: picked(entry, CHECK_FIELDS) for key, entry in document["checks"].items()},
        "decisions": [picked(entry, DECISION_FIELDS) for entry in document["decisions"]],
        "details": {topic: [with_stored_cites(entry, ("text",)) for entry in entries] for topic, entries in document["details"].items()},
        "corrections": [with_stored_cites(entry, ("was", "now")) for entry in document["corrections"]],
        "highlights": [with_stored_cites(entry, ("text",)) for entry in document["highlights"]],
        "coverage_notes": [picked(entry, COVERAGE_FIELDS) for entry in document.get("coverage_notes", [])],
    }
