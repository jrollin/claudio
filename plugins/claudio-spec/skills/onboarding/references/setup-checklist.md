# Running It Locally

The run-it deliverable: a repo-specific, copy-pasteable checklist to go from clone to a running, smoke-tested app, plus the fast pre-PR confidence loop.

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
   - **Cloud-native repos** rarely run as a local process. Substitute the real loop: cloud credentials/profile + target account/region, local emulation if supported (`serverless offline`, `sam local invoke`, `func start`, `cloud run` emulators), or deploy to a sandbox stage (`sls deploy --stage <dev>`, `cdk deploy`, `terraform apply`). Cite the IaC manifest and which stage is safe for a new dev.
7. **Smoke test** — one command or request that exercises a key flow end-to-end and shows the app works (e.g. `curl localhost:3000/health`, a CLI invocation, a single e2e test, or invoking a deployed function and checking its log/response).

### Fast pre-PR confidence loop

After the run/smoke steps, give the exact commands to run before opening a PR, ordered cheapest-first (lint → typecheck → unit → integration-if-local). Cite where each comes from (`package.json` scripts, `Makefile`, CI). Exclude anything needing a deployed environment. The Navigating-the-Code section describes *how* tests are organized; this is the *commands* to run.

```
<lint command>
<typecheck command>
<unit test command>
<integration test command>   # only if it runs locally without deployed infra
```

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

### Run                       # local process — OR the cloud loop below
$ <run server>               # from <file>
$ <run worker>               # from <file>  (omit if none)
$ <run UI>                   # from <file>  (omit if none)

### Deploy / emulate           # cloud-native repos only; replaces Run
$ <auth + select account/region>   # from README / IaC
$ <local emulation OR deploy to sandbox stage>   # from <IaC manifest>

### Smoke test
$ <command that proves it works>
```

## Rules

- Every command traces to a file in the repo. No invented steps.
- Omit sections that don't apply (no worker → no worker line); don't pad.
- The smoke test must exercise a real flow, not just print a version.
