#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# LLM-as-judge evaluation harness for claudio-craft agent ROUTING.
#
# Adapted from: skills/skill-testing/templates/eval.sh
#
# What this tests: the DISPATCH decision, not what an agent concludes once
# dispatched. The agent under test sees ONLY the `description` frontmatter of
# each agent in agents/ (exactly what a real dispatcher sees) and must answer
# with the set of agents it would dispatch. A judge scores set membership.
#
# Loading full agent bodies would test something the real dispatcher never
# sees, so this harness deliberately extracts descriptions only.
#
# Scope limit: only agents/ is loaded, no skill roster. So negative-routing
# scenarios assert that NO review agent is selected; they cannot require the
# dispatcher to name a specific skill it was never shown.
#
# Supports two CLI backends:
#   - claude (Claude Code CLI) — default
#   - opencode (OpenCode CLI) — use --backend opencode
#
# Requirements:
#   - claude CLI or opencode CLI
#   - python3 + pyyaml: pip3 install pyyaml
#   - jq: brew install jq
#
# Usage (paths shown from the plugin root, claudio-craft/):
#   bash tests/eval.sh                      # run all (claude)
#   bash tests/eval.sh --backend opencode   # run all (opencode)
#   bash tests/eval.sh --id <scenario_id>   # run one
#   bash tests/eval.sh --tag fanout         # run by tag
#   bash tests/eval.sh --dry-run            # show prompts only
#   bash tests/eval.sh --model <model>      # override model
#
# Tags: single, fanout, disambiguation, negative-routing, boundary
#
# Models:
#   claude backend:   model aliases (e.g. sonnet, opus) — default: sonnet
#   opencode backend: full model IDs required (e.g. anthropic/claude-sonnet-4-6)
#
# Cost: ~$0.01-0.03 per scenario (depending on model)
# ============================================================================

# ============================================================================
# CONFIG
# ============================================================================

SUITE_NAME="claudio-craft agent routing"

EVAL_BACKEND_VAR="CRAFT_ROUTING_EVAL_BACKEND"
EVAL_MODEL_VAR="CRAFT_ROUTING_EVAL_MODEL"

# The agent under test lists agent names only. Keeping the output shape tight
# makes set-membership judging unambiguous.
AGENT_INSTRUCTION="You are routing a user request to zero or more of the agents listed above, based ONLY on their descriptions.

Respond in exactly this format:
DISPATCH: <comma-separated agent names, or NONE>
WHY: <one short sentence>

Rules:
- Select every agent whose description covers a dimension the request names.
- Select no agent whose description disclaims the request (its 'NOT for' clause).
- If the request belongs to a skill rather than a review agent, write the skill name on the DISPATCH line and say so in WHY.
- If the request is too vague to route, write DISPATCH: NONE and ask what dimension is wanted in WHY.
- Do not review any code. Do not use tools. Do not explain beyond the one WHY sentence."

# ============================================================================
# SHARED HARNESS
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTS_DIR="$PLUGIN_DIR/agents"
GOLDEN="$SCRIPT_DIR/golden_examples.yaml"

BACKEND="${!EVAL_BACKEND_VAR:-claude}"
MODEL=""

FILTER_ID=""
FILTER_TAG=""
DRY_RUN=false
PASS=0
FAIL=0
SKIP=0

# --- arg parsing ---

needs_value() { if [[ $# -lt 2 ]]; then echo "Error: $1 requires a value"; exit 1; fi; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --id)      needs_value "$@"; FILTER_ID="$2"; shift 2 ;;
        --tag)     needs_value "$@"; FILTER_TAG="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --model)   needs_value "$@"; MODEL="$2"; shift 2 ;;
        --backend) needs_value "$@"; BACKEND="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# --- validate backend ---

case "$BACKEND" in
    claude|opencode) ;;
    *) echo "Error: unknown backend '$BACKEND' (use claude or opencode)"; exit 1 ;;
esac

# --- default model per backend ---

if [ -z "$MODEL" ]; then
    MODEL="${!EVAL_MODEL_VAR:-sonnet}"
    if [ "$BACKEND" = "opencode" ] && [ "$MODEL" = "sonnet" ]; then
        echo "Error: opencode requires a full model ID (e.g. anthropic/claude-sonnet-4-6)."
        echo "  Use: --model anthropic/claude-sonnet-4-6"
        exit 1
    fi
fi

# --- dependency checks ---

if [ "$BACKEND" = "opencode" ]; then
    REQUIRED_CLI="opencode"
else
    REQUIRED_CLI="claude"
fi

for cmd in "$REQUIRED_CLI" python3 jq perl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is required."
        [ "$cmd" = "claude" ] && echo "  Install: https://docs.anthropic.com/en/docs/claude-code"
        [ "$cmd" = "opencode" ] && echo "  Install: https://opencode.ai"
        [ "$cmd" = "python3" ] && echo "  Also needs: pip3 install pyyaml"
        [ "$cmd" = "jq" ] && echo "  Install: brew install jq"
        [ "$cmd" = "perl" ] && echo "  Used by strip_ansi/strip_system_tags on every response"
        exit 1
    fi
done

if ! python3 -c "import yaml" 2>/dev/null; then
    echo "Error: pyyaml is required."
    echo "  Install: pip3 install pyyaml"
    exit 1
fi

# --- YAML to JSON via python3 ---

yaml_to_json() {
    python3 -c "
import sys, json
try:
    import yaml
    data = yaml.safe_load(open(sys.argv[1]))
except ImportError:
    print('Error: pip3 install pyyaml', file=sys.stderr)
    sys.exit(1)
print(json.dumps(data))
" "$1"
}

if [ ! -f "$GOLDEN" ]; then
    echo "Error: golden examples not found: $GOLDEN"
    exit 1
fi

GOLDEN_JSON=$(yaml_to_json "$GOLDEN")
SCENARIO_COUNT=$(echo "$GOLDEN_JSON" | jq 'length')

# --- load agent descriptions ---
# Extracts `name` + `description` from each agents/*.md frontmatter. Uses a
# line-oriented parse rather than a YAML load: these descriptions contain
# unquoted "colon-space" (e.g. "Reads source: imports"), which strict YAML
# rejects but the Claude Code frontmatter parser accepts.

if [ ! -d "$AGENTS_DIR" ]; then
    echo "Error: agents directory not found: $AGENTS_DIR"
    exit 1
fi

# Fails hard on any unparseable agent file rather than skipping it: a silently
# short roster makes every scenario that needed the missing agent report a
# routing FAIL, which reads as a description regression instead of a bad parse.
AGENT_ROSTER=$(python3 -c "
import glob, os, re, sys

agents_dir = sys.argv[1]
out, errors = [], []
paths = sorted(glob.glob(os.path.join(agents_dir, '*.md')))
if not paths:
    print('Error: no agent files found in ' + agents_dir, file=sys.stderr)
    sys.exit(1)
for path in paths:
    base = os.path.basename(path)
    text = open(path).read()
    if not text.startswith('---'):
        errors.append(base + ': no frontmatter delimiter')
        continue
    fm = text.split('---', 2)[1]
    name = re.search(r'^name:\s*(.+)\$', fm, re.M)
    desc = re.search(r'^description:\s*(.+)\$', fm, re.M)
    if not name:
        errors.append(base + ': no name: field in frontmatter')
        continue
    if not desc:
        errors.append(base + ': no description: field in frontmatter')
        continue
    d = desc.group(1).strip()
    # A YAML block scalar ('>', '>-', '|') means the text is on following lines,
    # which this line-oriented parse cannot read. Refuse rather than emit an
    # agent whose description is the literal '>-'.
    if d in ('>', '>-', '|', '|-', '&gt;', '&gt;-'):
        errors.append(base + ': description uses a block scalar (' + d + '), needs a single-line value')
        continue
    out.append('- ' + name.group(1).strip() + ': ' + d)
if errors:
    print('Error: unparseable agent frontmatter:', file=sys.stderr)
    for e in errors:
        print('  - ' + e, file=sys.stderr)
    sys.exit(1)
print('\n\n'.join(out))
" "$AGENTS_DIR") || exit 1

AGENT_COUNT=$(printf '%s\n' "$AGENT_ROSTER" | grep -c '^- ' || true)
ROSTER_CHARS=${#AGENT_ROSTER}

# --- output sanitization ---

strip_ansi() {
    perl -pe 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\x1b\][^\x07]*\x07//g; s/\x1b\[\?[0-9;]*[a-zA-Z]//g'
}

strip_system_tags() {
    perl -0777 -pe 's/<system-reminder>.*?<\/system-reminder>//gs'
}

# --- safe temp file removal ---

SAFE_TMPDIR="${TMPDIR:-/tmp}"
SAFE_TMPDIR="${SAFE_TMPDIR%/}"
if [[ "$SAFE_TMPDIR" = "/" || -z "$SAFE_TMPDIR" ]]; then
    SAFE_TMPDIR="/tmp"
fi

rm_tmp() {
    local f="$1"
    case "$f" in
        "$SAFE_TMPDIR"/*) rm -f "$f" ;;
        *) echo "WARN: refusing to delete non-temp file: $f" >&2 ;;
    esac
}

# --- LLM invocation ---

# Preserves the CLI's real exit code and surfaces its stderr: an auth failure or
# bad --model must not be silently judged as a routing FAIL.
# --system-prompt (not --append-) plus --tools "" keep the dispatcher's context to
# the agent descriptions alone, which is the whole premise of this harness.
llm_call() {
    local prompt="$1"
    local system_prompt="${2:-}"
    local stderr_file raw_output exit_code

    stderr_file=$(mktemp "$SAFE_TMPDIR/craft-routing-eval.XXXXXX")

    if [ "$BACKEND" = "opencode" ]; then
        if [ -n "$system_prompt" ]; then
            prompt="$system_prompt

---

$prompt"
        fi

        exit_code=0
        raw_output=$(opencode run \
            --model "$MODEL" \
            --title "craft-routing-eval" \
            "$prompt" 2>"$stderr_file") || exit_code=$?

        if [ "$exit_code" -ne 0 ]; then
            echo "ERROR: opencode exited with code $exit_code (model: $MODEL)" >&2
            cat "$stderr_file" >&2
            rm_tmp "$stderr_file"
            return 1
        fi
        rm_tmp "$stderr_file"
        printf '%s\n' "$raw_output" | strip_ansi | strip_system_tags | sed '/^> .* · /d' | sed '/^[[:space:]]*$/d'
    else
        exit_code=0
        if [ -n "$system_prompt" ]; then
            raw_output=$(claude \
                --print \
                --model "$MODEL" \
                --system-prompt "$system_prompt" \
                --tools "" \
                --no-session-persistence \
                "$prompt" 2>"$stderr_file") || exit_code=$?
        else
            raw_output=$(claude \
                --print \
                --model "$MODEL" \
                --tools "" \
                --no-session-persistence \
                "$prompt" 2>"$stderr_file") || exit_code=$?
        fi

        if [ "$exit_code" -ne 0 ]; then
            echo "ERROR: claude exited with code $exit_code (model: $MODEL)" >&2
            cat "$stderr_file" >&2
            rm_tmp "$stderr_file"
            return 1
        fi
        rm_tmp "$stderr_file"
        # Drop blank lines: stripping a <system-reminder> block leaves an empty
        # leading line, which would otherwise become the extracted verdict.
        printf '%s\n' "$raw_output" | strip_system_tags | sed '/^[[:space:]]*$/d'
    fi
}

# --- scenario evaluation ---

evaluate_scenario() {
    local idx="$1"

    local id description query context anti_patterns reasoning tags
    local expected_behavior
    id=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].id")
    description=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].description")
    query=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].user_query")
    context=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].context // \"\"")
    expected_behavior=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].expected.behavior // \"\"")
    anti_patterns=$(echo "$GOLDEN_JSON" | jq -r "(.[$idx].anti_patterns // []) | join(\"\n- \")" 2>/dev/null || echo "")
    reasoning=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].expected.reasoning")
    tags=$(echo "$GOLDEN_JSON" | jq -r "(.[$idx].tags // [])[]" 2>/dev/null || echo "")

    if [ -n "$FILTER_ID" ] && [ "$id" != "$FILTER_ID" ]; then
        return
    fi
    if [ -n "$FILTER_TAG" ]; then
        if ! echo "$tags" | grep -qF "$FILTER_TAG"; then
            return
        fi
    fi

    echo "--- Scenario: $id ---"
    echo "  $description"
    echo "  Query: $query"

    local agent_system agent_user
    agent_system="You are the agent dispatcher for a Claude Code plugin. These are the available agents and their descriptions:

$AGENT_ROSTER

--- END AGENT LIST ---

$AGENT_INSTRUCTION"

    agent_user="$query"
    if [ -n "$context" ]; then
        agent_user="$context

$query"
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would send to $MODEL ($BACKEND)"
        echo "  System: ($AGENT_COUNT agent descriptions, $ROSTER_CHARS chars)"
        echo "  User: $agent_user"
        echo ""
        SKIP=$((SKIP + 1))
        return
    fi

    local agent_response
    agent_response=$(llm_call "$agent_user" "$agent_system") || {
        echo "  ERROR: Agent call failed"
        FAIL=$((FAIL + 1))
        echo ""
        return
    }

    if [ -z "$agent_response" ]; then
        echo "  ERROR: Empty agent response (CLI may be out of quota)"
        FAIL=$((FAIL + 1))
        echo ""
        return
    fi

    # Judge: set membership, not first-item ordering.
    local judge_prompt verdict judge_response
    judge_prompt="You are a routing evaluator. Score the dispatcher's agent selection as PASS or FAIL.

Judging rules:
- Compare the SET of agents on the DISPATCH line against the expected selection.
- Ordering does not matter. Only set membership matters.
- FAIL if any REQUIRED agent is missing from the selection.
- FAIL if any FORBIDDEN agent appears in the selection.
- Over-selecting ('dispatch everything to be safe') is a FAIL whenever the
  expected behavior forbids a specific agent or forbids a broad fan-out.
- The WHY sentence is context only. Score the DISPATCH line.

Respond with exactly one line: PASS or FAIL, followed by a colon and a brief reason.

Do not use tools. Do not write code. Just evaluate.

---

User query:
$agent_user

Dispatcher response:
$agent_response

Expected selection:
$expected_behavior

Anti-patterns (selection must NOT match these):
- $anti_patterns

Reasoning:
$reasoning"

    judge_response=$(llm_call "$judge_prompt") || {
        echo "  ERROR: Judge call failed"
        FAIL=$((FAIL + 1))
        echo ""
        return
    }

    if [ -z "$judge_response" ]; then
        echo "  ERROR: Empty judge response (CLI may be out of quota)"
        FAIL=$((FAIL + 1))
        echo ""
        return
    fi

    # First line that actually states a verdict, not blindly line 1: a judge
    # preamble or a leftover blank line would otherwise read as a FAIL.
    verdict=$(printf '%s\n' "$judge_response" | grep -m1 -iE '^[[:space:]]*(PASS|FAIL)\b' || true)

    if [ -z "$verdict" ]; then
        echo "  ERROR: Judge returned no PASS/FAIL verdict"
        echo "  Judge said:"
        printf '%s\n' "$judge_response" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
        echo ""
        return
    fi

    if printf '%s\n' "$verdict" | grep -qiE "^[[:space:]]*PASS"; then
        printf '  PASS: %s\n' "$verdict"
        PASS=$((PASS + 1))
    else
        printf '  FAIL: %s\n' "$verdict"
        echo "  Dispatcher said:"
        printf '%s\n' "$agent_response" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    fi
    echo ""
}

# --- main ---

echo "=== $SUITE_NAME evaluation ==="
echo "Backend: $BACKEND"
echo "Model: $MODEL"
echo "Agents: $AGENT_COUNT"
echo "Scenarios: $SCENARIO_COUNT"
echo ""

for ((i=0; i<SCENARIO_COUNT; i++)); do
    evaluate_scenario "$i"
done

echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="

# A mistyped --id/--tag must not look like a green run. Scenario ids are long
# snake_case strings, so a filter that matches nothing is a user error, not a pass.
if [ $((PASS + FAIL + SKIP)) -eq 0 ]; then
    if [ -n "$FILTER_ID" ] || [ -n "$FILTER_TAG" ]; then
        echo "Error: no scenario matched the filter (--id '${FILTER_ID:-}' --tag '${FILTER_TAG:-}')." >&2
        echo "  Available ids:  $(echo "$GOLDEN_JSON" | jq -r '.[].id' | paste -sd' ' -)" >&2
        echo "  Available tags: $(echo "$GOLDEN_JSON" | jq -r '(.[].tags // [])[]' | sort -u | paste -sd' ' -)" >&2
    else
        echo "Error: no scenarios ran." >&2
    fi
    exit 1
fi

[ "$FAIL" -eq 0 ] || exit 1
