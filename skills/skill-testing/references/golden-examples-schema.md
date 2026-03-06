# Golden Examples Schema

YAML schema for skill behavioral test scenarios. Used with `eval.sh` (LLM-as-judge).

## Schema

```yaml
- id: unique_snake_case_id
  description: What this scenario tests (one line)
  user_query: "The user's message to the agent"
  context: |                          # optional — state/context before the query
    Additional context provided to the agent.
  expected:
    behavior: >                       # option A: prose description of correct behavior
      Agent does X, not Y.
    tool_calls:                       # option B: list of expected CLI commands
      - 'command arg1 "arg2"'
    reasoning: >                      # why this is correct per the skill
      Skill section X says "...".
  anti_patterns:                      # things agent must NOT do as primary action
    - Doing X before Y
    - Skipping step Z
  tags: [category1, category2]        # for --tag filtering
```

## Field Rules

| Field | Required | Notes |
|---|---|---|
| `id` | Yes | Unique across file. Snake_case. Used with `--id` filter. |
| `description` | Yes | One line. Shown in eval output. |
| `user_query` | Yes | Exactly what the user says. Keep short and unambiguous. |
| `context` | No | State the phase, existing code, prior actions. Avoids ambiguity. |
| `expected.behavior` | One of A/B | Prose. Judge evaluates agent response against this. |
| `expected.tool_calls` | One of A/B | List of CLI commands. Judge checks FIRST command matches. |
| `expected.reasoning` | Yes | Links back to specific skill wording. Helps the judge. |
| `anti_patterns` | Yes | List. Judge checks agent's PRIMARY action doesn't match these. |
| `tags` | Yes | List. At least one tag per scenario for `--tag` filtering. |

## Which Expected Field to Use

| Skill type | Field | Example |
|---|---|---|
| Command routing | `expected.tool_calls` | cartog: `['cartog rag search "auth"']` |
| Behavioral | `expected.behavior` | TDD: "Agent writes failing test before implementation" |
| Mixed | Both fields | Judge uses `tool_calls` if present, else `behavior` |

## Writing Good Scenarios

### Make queries unambiguous

Bad:
```yaml
user_query: "Write the implementation."
```

Good:
```yaml
user_query: "The test is failing as expected (RED phase complete). Now make it green."
context: |
  We are in the GREEN phase. There is exactly one failing test:
  ...
  This is the only test. No other tests exist.
```

### Expected behavior must be judge-verifiable

Bad — too vague:
```yaml
behavior: "Agent follows TDD correctly."
```

Bad — too strict on phrasing:
```yaml
behavior: "Agent says 'return true' and explicitly states it is deferring edge cases."
```

Good — focuses on the decision:
```yaml
behavior: >
  Agent proposes `return true` as the implementation.
  It must NOT suggest a regex or any conditional logic.
```

### Anti-patterns target the primary action

Bad — too broad:
```yaml
anti_patterns:
  - Mentioning regex at any point
```

Good — targets the decision:
```yaml
anti_patterns:
  - Writing a regex validator when only one happy-path test exists
  - Adding logic for edge cases not yet covered by a test
```

## Example: Behavioral Skill (TDD)

```yaml
- id: write_test_before_code
  description: New feature — agent must write failing test first
  user_query: "Implement a function `add(a, b)` that returns the sum."
  expected:
    behavior: >
      Agent describes writing a failing test for add() first,
      running it to watch it fail, then writing the minimal implementation.
    reasoning: >
      Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
  anti_patterns:
    - Writing the implementation before describing the test
    - Providing a complete implementation without mentioning a test
  tags: [iron-law]
```

## Example: Command Routing Skill (cartog)

```yaml
- id: search_natural_language
  description: Natural language query uses rag search first
  user_query: "Find the code that handles authentication token validation"
  expected:
    tool_calls:
      - 'cartog rag search "authentication token validation"'
    reasoning: >
      Natural language query describing behavior. First command must be rag search.
  anti_patterns:
    - cartog search as the FIRST command
    - Running cartog search BEFORE or IN PARALLEL with rag search
  tags: [routing]
```

## Organizing Scenarios

Group related scenarios with YAML comments:

```yaml
# ============================================================
# Category: Iron Law
# ============================================================

- id: ...

# ============================================================
# Category: Exceptions
# ============================================================

- id: ...
```
