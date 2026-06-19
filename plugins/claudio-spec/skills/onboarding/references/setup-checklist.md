# Local Setup Checklist

The third onboarding deliverable: a repo-specific, copy-pasteable checklist to go from clone to a running, smoke-tested app.

## Method

1. Read every setup source: `README`, `CONTRIBUTING`, `Makefile`, package/build manifests, `scripts/`, `.devcontainer/`, `docker-compose.yml`, `.env.example`, `.tool-versions` / `.nvmrc` / `rust-toolchain.toml`.
2. Derive each step from one of those files. If a step can't be justified from a file, omit it.

## Required Output

An ordered checklist with the exact command for each step:

1. **Required runtimes** — language version(s) and tooling, from `.tool-versions`, `.nvmrc`, `engines`, `rust-toolchain.toml`, etc.
2. **Dependency install** — the install command (`npm ci`, `pnpm install`, `pip install -e .`, `cargo build`, `bundle install`).
3. **Environment variables** — copy `.env.example`, list required vars and where they're documented.
4. **Database setup** — start the DB (compose service, local install), create the database.
5. **Migrations / seeds** — the commands to apply schema and seed data.
6. **Run commands** — server, worker, and UI separately if they're distinct processes. Cite the script/target for each.
7. **Smoke test** — one command or request that exercises a key flow end-to-end and shows the app works (e.g. `curl localhost:3000/health`, a CLI invocation, a single e2e test).

## Template

```
## Local Setup

### Prerequisites
- <runtime> <version>        # from <file>

### Install
$ <install command>          # from <file>

### Configure
$ cp .env.example .env       # set: VAR_A, VAR_B (see <file>)  (omit if no .env.example)

### Database
$ <start db>                 # from docker-compose.yml / README
$ <run migrations>           # from <file>
$ <seed>                     # from <file>  (omit if none)

### Run
$ <run server>               # from <file>
$ <run worker>               # from <file>  (omit if none)
$ <run UI>                   # from <file>  (omit if none)

### Smoke test
$ <command that proves it works>
```

## Rules

- Every command traces to a file in the repo. No invented steps.
- Omit sections that don't apply (no worker → no worker line); don't pad.
- The smoke test must exercise a real flow, not just print a version.
