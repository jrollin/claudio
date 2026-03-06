#!/usr/bin/env bash
set -euo pipefail

# LLM-as-judge evaluation for TDD skill behavioral tests.
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
# Usage:
#   bash skills/tdd/tests/eval.sh                              # run all (claude)
#   bash skills/tdd/tests/eval.sh --backend opencode           # run all (opencode)
#   bash skills/tdd/tests/eval.sh --id write_test_before_code  # run one
#   bash skills/tdd/tests/eval.sh --tag iron-law               # run by tag
#   bash skills/tdd/tests/eval.sh --dry-run                    # show prompts only
#   bash skills/tdd/tests/eval.sh --model sonnet               # use a different model
#
# Models:
#   claude backend:   model aliases (e.g. sonnet, opus) — default: sonnet
#   opencode backend: full model IDs required (e.g. anthropic/claude-sonnet-4-6)
#
# Cost: ~$0.01-0.03 per scenario (depending on model)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_MD="$SKILL_DIR/SKILL.md"
ANTI_PATTERNS_MD="$SKILL_DIR/testing-anti-patterns.md"
GOLDEN="$SCRIPT_DIR/golden_examples.yaml"

BACKEND="${TDD_EVAL_BACKEND:-claude}"
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
    MODEL="${TDD_EVAL_MODEL:-sonnet}"
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

for cmd in "$REQUIRED_CLI" python3 jq; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is required."
        [ "$cmd" = "claude" ] && echo "  Install: https://docs.anthropic.com/en/docs/claude-code"
        [ "$cmd" = "opencode" ] && echo "  Install: https://opencode.ai"
        [ "$cmd" = "python3" ] && echo "  Also needs: pip3 install pyyaml"
        [ "$cmd" = "jq" ] && echo "  Install: brew install jq"
        exit 1
    fi
done

if ! python3 -c "import yaml" 2>/dev/null; then
    echo "Error: pyyaml is required."
    echo "  Install: pip3 install pyyaml"
    exit 1
fi

# --- YAML to JSON via python3 ---
# Golden examples are YAML (human-editable, comments, multi-line strings).
# Converted to JSON once at startup so jq can query individual scenarios.

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

GOLDEN_JSON=$(yaml_to_json "$GOLDEN")
SCENARIO_COUNT=$(echo "$GOLDEN_JSON" | jq 'length')

# --- load skill content ---

SKILL_CONTENT=$(cat "$SKILL_MD")
ANTI_PATTERNS_CONTENT=$(cat "$ANTI_PATTERNS_MD")

# --- output sanitization ---

strip_ansi() {
    perl -pe 's/\x1b\[[0-9;]*[a-zA-Z]//g; s/\x1b\][^\x07]*\x07//g; s/\x1b\[\?[0-9;]*[a-zA-Z]//g'
}

# Strip <system-reminder>...</system-reminder> tags injected by claude CLI
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

# --- LLM call abstraction ---
#
# For opencode: system prompt is embedded in user message (no --system-prompt flag).

llm_call() {
    local prompt="$1"
    local system_prompt="${2:-}"
    local stderr_file raw_output exit_code

    stderr_file=$(mktemp)

    if [ "$BACKEND" = "opencode" ]; then
        if [ -n "$system_prompt" ]; then
            prompt="$system_prompt

---

$prompt"
        fi

        exit_code=0
        raw_output=$(opencode run \
            --model "$MODEL" \
            --title "tdd-eval" \
            "$prompt" 2>"$stderr_file") || exit_code=$?

        if [ "$exit_code" -ne 0 ]; then
            echo "ERROR: opencode exited with code $exit_code" >&2
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
            echo "ERROR: claude exited with code $exit_code" >&2
            cat "$stderr_file" >&2
            rm_tmp "$stderr_file"
            return 1
        fi
        rm_tmp "$stderr_file"
        printf '%s\n' "$raw_output" | strip_system_tags
    fi
}

# --- evaluate one scenario ---

evaluate_scenario() {
    local idx="$1"

    local id description query context expected_behavior anti_patterns reasoning tags
    id=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].id")
    description=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].description")
    query=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].user_query")
    context=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].context // \"\"")
    expected_behavior=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].expected.behavior")
    anti_patterns=$(echo "$GOLDEN_JSON" | jq -r "(.[$idx].anti_patterns // []) | join(\"\n- \")" 2>/dev/null || echo "")
    reasoning=$(echo "$GOLDEN_JSON" | jq -r ".[$idx].expected.reasoning")
    tags=$(echo "$GOLDEN_JSON" | jq -r "(.[$idx].tags // [])[]" 2>/dev/null || echo "")

    # Apply filters
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

    # Build agent prompt — constrained to produce a short numbered list
    local agent_system agent_user
    agent_system="You are a software engineering assistant. You have the following TDD skill loaded:

--- TDD SKILL ---
$SKILL_CONTENT

--- TESTING ANTI-PATTERNS ---
$ANTI_PATTERNS_CONTENT
--- END SKILL ---

Based on this skill, respond to the user's request by listing the steps you would take in order. List each step on its own line prefixed with a number. Be concise — one sentence per step. Do not write code. Do not use tools."

    agent_user="$query"
    if [ -n "$context" ]; then
        agent_user="$context

$query"
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would send to $MODEL ($BACKEND)"
        echo "  System: (skill loaded, ${#SKILL_CONTENT} chars + ${#ANTI_PATTERNS_CONTENT} chars anti-patterns)"
        echo "  User: $agent_user"
        echo ""
        SKIP=$((SKIP + 1))
        return
    fi

    # Step 1: Agent call — simulate the LLM with skill loaded
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

    # Step 2: Judge call — evaluate TDD compliance
    local judge_prompt verdict judge_response
    judge_prompt="You are a TDD compliance evaluator. Score the agent response as PASS or FAIL.

Judging rules:
- PASS = the agent's response demonstrates correct TDD behavior as described in expected behavior.
- FAIL = the agent's response contradicts the expected behavior or exhibits an anti-pattern.
- Evaluate the agent's response IN THE CONTEXT of the user query. The query specifies which TDD phase applies.
- If the query says the RED phase is complete or a test is already failing, the agent should NOT rewrite the test — it should proceed to GREEN.
- If the scenario is about an exception (config file, throwaway prototype), PASS means the agent correctly identifies and handles the exception.

Respond with exactly one line: PASS or FAIL, followed by a colon and a brief reason.

Do not use tools. Do not write code. Just evaluate.

---

User query:
$agent_user

Agent response:
$agent_response

Expected behavior:
$expected_behavior

Anti-patterns (agent must NOT exhibit these as its primary action):
- $anti_patterns

Reasoning (why the expected behavior is correct per TDD):
$reasoning"

    judge_response=$(llm_call "$judge_prompt") || {
        echo "  ERROR: Judge call failed"
        FAIL=$((FAIL + 1))
        echo ""
        return
    }

    verdict=$(printf '%s\n' "$judge_response" | head -1)

    if printf '%s\n' "$verdict" | grep -qi "^PASS"; then
        printf '  PASS: %s\n' "$verdict"
        PASS=$((PASS + 1))
    else
        printf '  FAIL: %s\n' "$verdict"
        echo "  Agent said:"
        printf '%s\n' "$agent_response" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    fi
    echo ""
}

# --- main ---

echo "=== TDD skill evaluation ==="
echo "Backend: $BACKEND"
echo "Model: $MODEL"
echo "Scenarios: $SCENARIO_COUNT"
echo ""

for ((i=0; i<SCENARIO_COUNT; i++)); do
    evaluate_scenario "$i"
done

echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="

[ "$FAIL" -eq 0 ] || exit 1
