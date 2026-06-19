# Testing Strategy

The second onboarding deliverable: how this repo tests itself, and the fastest way to gain confidence before a PR.

## Method

1. Locate test files and config (`*.test.*`, `*_test.*`, `*_spec.*`, `tests/`, `spec/`, `jest.config`, `vitest.config`, `pytest.ini`, `Cargo.toml [dev-dependencies]`, CI workflows).
2. Read the CI config (`.github/workflows/`, `.gitlab-ci.yml`, etc.) — it's the authoritative source for what "passing" means.
3. Infer the test pyramid shape from where tests live and what they touch.

## Required Output

### Where tests live and how they're organized

- Layout: co-located vs. separate `tests/` tree.
- Levels present: unit / integration / e2e — cite an example file of each.

### Fastest local confidence loop

The exact commands to run before opening a PR, ordered cheapest-first (lint → typecheck → unit → integration). Cite where each comes from (`package.json` scripts, `Makefile`, CI).

```
<lint command>
<typecheck command>
<unit test command>
<integration test command>   # if it runs locally without deployed infra
```

### Fixtures, mocks, testcontainers

- How test data is built (factories, fixtures, seeds).
- What's mocked vs. real (mock only at system boundaries: network, time, randomness).
- Whether testcontainers / a test DB is used, and how it's started.

### Common failure modes

From config/docs, note known foot-guns: flaky timing, ordering dependence, environment leakage (e.g. system binaries on PATH), services that must be running first.

## Fallback: no testing strategy exists

If the repo has little or no testing, propose a plan following the testing pyramid:

- **Many unit tests** — pure logic, fast, no I/O.
- **Fewer integration tests** — component interactions, real DB via testcontainers, external services mocked.
- **Fewest e2e tests** — critical user flows only.

Name the first 2–3 concrete test files to add, anchored to the highest-risk code you found in the architecture map.

## Rules

- The "fast loop" must be runnable locally — exclude steps that need a deployed environment.
- Cite the source of every command.
- Don't claim a level exists without an example file proving it.
