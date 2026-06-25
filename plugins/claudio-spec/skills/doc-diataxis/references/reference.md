> Reference for: doc-diataxis
> Load when: authoring a Reference

# Reference

**Serves:** a working user who needs to *look up a fact*. Cognition + application.

Reference material is the technical description of the machinery: the facts, in a form you can consult mid-task and trust literally. Think encyclopedia entry, not lesson. Success is the reader finding the precise fact quickly and correctly.

## Voice and stance

- Neutral, descriptive, austere. Describe; do not instruct or persuade.
- State what *is*, not what to *do*: "`timeout` is the request timeout in seconds (default 30)", not "set `timeout` to a sensible value".
- Authoritative and consistent — the reader relies on it being exactly right.

## Structure

- **Mirror the structure of the product/code.** If the code has modules → classes → methods, the reference follows that shape. Predictable structure is how readers navigate.
- **Consistent, repeating format** for like things. Every function entry has the same fields in the same order (signature, params, returns, errors, example). Every config key likewise.
- **Scannable** — tables, definition lists, headings. Optimized for jump-in/jump-out, not linear reading.

## Must include

- Complete, accurate facts: signatures, parameters with types and defaults, return values, error codes, config keys, endpoints, constraints.
- Whatever a user needs to *confirm* something while working.
- Short, illustrative examples that show usage without teaching.

## Must exclude (these belong elsewhere)

- **Instructions / procedures** — "to do X, first…". → how-to
- **Teaching** — no hand-holding. → tutorial
- **Opinions, rationale, trade-offs** — "we recommend…", "this is better because…". → explanation
- **Narrative** — reference is consulted, not read start to finish.

## The accuracy rule (non-negotiable)

**Every fact must come from a verifiable source — code, schema, spec, or authoritative doc — never from memory.** Readers trust reference content literally; a wrong default or a misspelled flag causes real failures.

- Verify signatures, defaults, flag names, endpoints, and error codes against the actual source.
- If a fact can't be verified, mark it `‹unverified›` and list it as an open question. Do **not** guess a value.
- Prefer generating reference from the source of truth where possible (docstrings, schema, OpenAPI) so it can't drift.

## Title pattern

Noun-phrase naming the thing: "Configuration reference", "CLI reference", "`auth` API reference", "Environment variables".

## Smell test

- Could a reader find one specific fact in seconds?
- Is the structure a faithful mirror of the product?
- Is every entry formatted identically to its peers?
- Is every fact traceable to a source (and unverifiable ones flagged)?
- Did you avoid instructing, teaching, and editorializing?
