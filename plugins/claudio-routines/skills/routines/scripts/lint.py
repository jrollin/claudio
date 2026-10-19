import argparse
import itertools
import json
import re

ALLOWED_HOSTS = {"claude.ai", "github.com"}
URL_HOST = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://(?:[^\s/@]*@)?([A-Za-z0-9.-]+)")
BARE_HOST = re.compile(r"(?<![A-Za-z0-9.-])((?:[A-Za-z0-9-]+\.)+(?i:com|net|io|eu|ai|org))(?![A-Za-z0-9-])")
LITERAL_VALUE_MIN_LENGTH = 8
MARKER = "<!-- not runnable -->"
MARKER_NEAR_MISS = re.compile(r"\s*<!--.*not\s*runnable", re.IGNORECASE)
SETUP_RULES = ("host", "literal-number")
PUBLIC_RULES = (
    ("literal-number", re.compile(r"[0-9]{5,}")),
    ("channel-name", re.compile(r"#[a-z]")),
    ("threshold", re.compile(
        r"(?<![A-Za-z0-9_.])[0-9]+(?:\.[0-9]+)? ?(?:%|ms|s|min|h|MB|GB)(?![A-Za-z0-9_])"
        r"|\b(?i:above|below|over|under)\s+[0-9]"
    )),
)
REQUIRED_DENY = ("PushNotification", "Bash(sleep *)", "Monitor")
RUNTIME_SCRIPTS = ("state.py", "collect.py", "evaluate.py", "digest.py", "tribe.py", "recap.py")
SCRIPT_NAMES = "|".join(re.escape(name.removesuffix(".py")) for name in RUNTIME_SCRIPTS)
SCRIPT_CALL = re.compile(rf"(?<![\w.-])({SCRIPT_NAMES})\.py(?!\w)")
COMMAND = re.compile(r"[ \t]+(-*[A-Za-z0-9][A-Za-z0-9_-]*)")
CHAIN = re.compile(r"&&|\|\|?|;")
CALL_END = re.compile(r"\s*(?:$|&&|\|\|?|;)")
FLAG = re.compile(r"(?<![\w-])--[A-Za-z][A-Za-z0-9-]*")


def options_of(parser):
    return {option for action in parser._actions for option in action.option_strings}


def parser_contract(parser):
    commands = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            commands = {name: options_of(command) for name, command in action.choices.items()}
    return commands, options_of(parser)


def call_rules(line, match, end, contract):
    name = match.group(1)
    if contract is None:
        return [f"{name}-missing"]
    commands, options = contract
    start = match.end()
    if commands is not None:
        command = COMMAND.match(line, start)
        if command is None:
            return [f"{name}-command"] if CALL_END.match(line, start) else []
        options = commands.get(command.group(1))
        if options is None:
            return [f"{name}-command"]
        start = command.end()
    return [f"{name}-flag"] if any(flag not in options for flag in FLAG.findall(line, start, end)) else []


def contract_rules(line, contracts):
    calls = list(SCRIPT_CALL.finditer(line))
    rules = []
    for index, match in enumerate(calls):
        end = calls[index + 1].start() if index + 1 < len(calls) else len(line)
        chain = CHAIN.search(line, match.end(), end)
        rules += call_rules(line, match, chain.start() if chain else end, contracts.get(f"{match.group(1)}.py"))
    return rules


def public_rules(line):
    rules = [name for name, pattern in PUBLIC_RULES if pattern.search(line)]
    hosts = URL_HOST.findall(line) + BARE_HOST.findall(line)
    if any(host.lower() not in ALLOWED_HOSTS for host in hosts):
        rules.append("host")
    return rules


def setup_rules(line):
    return [rule for rule in public_rules(line) if rule in SETUP_RULES]


def no_rules(line):
    return []


def provider_rule(names):
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, names)) + r")\b", re.IGNORECASE) if names else None

    def rules(line):
        return ["provider-name"] if pattern is not None and pattern.search(line) else []

    return rules


def combined(*checks):
    return lambda line: [rule for check in checks for rule in check(line)]


def logical_lines(lines):
    start, parts = None, []
    for number, line in enumerate(lines, 1):
        start = start or number
        text = line.rstrip()
        parts.append(text.removesuffix("\\"))
        if not text.endswith("\\"):
            yield start, " ".join(parts)
            start, parts = None, []
    if parts:
        yield start, " ".join(parts)


def first_line(text):
    return text.removeprefix("\ufeff").split("\n", 1)[0].removesuffix("\r")


def is_marked(text):
    return first_line(text) == MARKER


def near_miss_marker(text):
    line = first_line(text)
    return line != MARKER and MARKER_NEAR_MISS.match(line) is not None


def line_findings(path, text, line_rules):
    return {(path, number, rule) for number, line in enumerate(text.splitlines(), 1) for rule in line_rules(line)}


def template_findings(path, text, line_rules, contracts):
    findings = line_findings(path, text, line_rules)
    findings.update(
        (path, number, rule)
        for number, line in logical_lines(text.splitlines())
        for rule in contract_rules(line, contracts)
    )
    if near_miss_marker(text):
        findings.add((path, 1, "marker"))
    return findings


def literal_values(text, values):
    literals = {
        key: value for key, value in values.items() if isinstance(value, str) and len(value) >= LITERAL_VALUE_MIN_LENGTH
    }
    return sorted(
        (number, key)
        for number, line in enumerate(text.splitlines(), 1)
        for key, value in literals.items()
        if value in line
    )


def repeated_values(values_by_routine):
    holders = {}
    for slug in sorted(values_by_routine):
        for key, value in values_by_routine[slug].items():
            holders.setdefault((key, json.dumps(value, sort_keys=True)), []).append(slug)
    return sorted(
        (first, second, key)
        for (key, _), slugs in holders.items()
        for first, second in itertools.combinations(slugs, 2)
    )


def settings_object(data):
    try:
        document = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def denied_entries(settings):
    permissions = settings.get("permissions")
    deny = permissions.get("deny") if isinstance(permissions, dict) else None
    entries = deny if isinstance(deny, list) else []
    return {entry for entry in entries if isinstance(entry, str)}


def settings_findings(path, data):
    if data is None:
        return {(path, 1, "settings-missing")}
    settings = settings_object(data)
    if settings is None:
        return {(path, 1, "settings-invalid")}
    denied = denied_entries(settings)
    return {(path, 1, f"deny-missing:{entry}") for entry in REQUIRED_DENY if entry not in denied}
