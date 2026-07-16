# Navigating the Code

After the reader has the big picture, this section teaches them to **find things and follow conventions** — where code lives, how it's named, how it's tested. Now (not before) a directory map earns its place, kept lean.

## Method

1. Map the top-level layout, then the source tree. Prefer `cartog_map`/`cartog_outline` if installed; else Glob the tree.
2. Read the CI config and test config to learn what "passing" means and how tests are organized.
3. Look for stated conventions in `CONTRIBUTING`, `AGENTS.md`, `CLAUDE.md`, lint config, and repeated file-naming patterns.

## Required Output

### Directory map (lean)

Top ~10 directories, each with a **responsibility and a why** — not an exhaustive tree, not every file. One citing example per row.

| Directory | Responsibility (why it exists) | Evidence |
|-----------|-------------------------------|----------|
| `src/Controller/` | business actions + auth per resource | `src/Controller/…` |
| `src/Service/Kpis/` | pure KPI compute formulas, one per KPI | `src/Service/Kpis/…` |

Keep it to what helps a dev *navigate*. The directory map lists **code folders**, not the L2 containers: no row should repeat an L2 container verbatim. A container groups one-or-more folders (e.g. an "Ingestion" container spans `Handler/Jobs/` + `Service/Rds/`); this map goes one level finer, naming those folders and what each holds.

### Conventions

The patterns a new dev must follow to fit in, each cited to a real example:

- **Naming** — file/class/test naming patterns (e.g. `*RecordsToRdsService`, `*.test.ts`, one service per KPI).
- **Layering rule** — the call direction the codebase enforces (e.g. Controller never touches the ORM directly; Manager is the only data-access layer). State it as the rule and cite a file that obeys it.
- **Wiring / DI** — how dependencies are assembled (a container file, a framework, manual construction). Cite it.
- **Config access** — the one blessed way to read env/config (a helper, not raw `process.env` scattered).

State absences too: "no enforced import boundaries — any module may import any other" is useful signal.

### Testing strategy

- **Where tests live & how organized** — co-located vs a `test/` tree mirroring `src/`; the levels present (unit / integration / functional / e2e), each with one example file.
  - For **cloud-native repos**, distinguish fakes vs real cloud: unit (SDK mocked), integration (real local backing service — DB-local / LocalStack / testcontainers), functional (one deployed service), e2e (cross-service, deployed). Note which levels need a deployed environment — they're excluded from the fast loop.
- **Fixtures / mocks / testcontainers** — how test data is built (factories, fixtures, seeds); what's mocked vs real (mock only at boundaries: network, time, randomness); whether a test DB/container is used and how it starts.
- **Coverage gate** if one is configured (cite the config).
- **Common failure modes** — flaky timing, ordering dependence, environment leakage (system binaries on PATH), a service that must be running first. Cite config/docs.

The **fast confidence loop** (the exact pre-PR commands) belongs in the Running It section, not here — reference it rather than duplicating.

## Fallback: little or no testing

Propose a plan following the pyramid: many unit (pure logic, no I/O), fewer integration (real DB via testcontainers, externals mocked), fewest e2e (critical flows). Name the first 2–3 concrete test files to add, anchored to the highest-risk code found in Big Picture.

## Rules

- The directory map is a navigation aid, not a full tree — top ~10, every row has a why.
- Every convention and test level is cited to a real example file; don't claim a level exists without one.
- Describe conventions as they are; don't propose new ones.
- State useful absences plainly (no layering rule, no tests for X).
