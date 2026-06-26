# CI/CD

An onboarding deliverable: how code gets from a branch to a running environment, so a new dev knows what runs on push, where it deploys, and how to ship safely. Describe what exists and cite it; don't redesign the pipeline.

## When this applies

Produce this section when the repo has CI/CD config: `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `.circleci/`, `azure-pipelines.yml`, `bitbucket-pipelines.yml`, or a deploy script wired to a hosting platform. If there is none, say so in one line and move on.

## Method

1. Read the workflow/pipeline files first — they are the source of truth for what "shipped" means.
2. Map each pipeline to its **trigger** (push to branch, PR, tag, manual/dispatch, schedule) and its **target environment**.
3. Distinguish CI (lint/test/build gates) from CD (deploy steps), and note which branch deploys where.

## Required Output

### Pipelines
One row per workflow: trigger → what it runs → where it deploys. A table reads best.

| Workflow | Trigger | Pipeline (steps) | Deploy → env |
|----------|---------|------------------|--------------|
| `ci.yml` | pull_request | lint → test → build | — |
| `deploy-prod.yml` | push `main` / tag | test → build → deploy | production |

### Branch → environment mapping
The promotion path in one glance (e.g. `PR → review app`, `sandbox → sdbx`, `staging → stag`, `main → prod`). Cite the trigger blocks. Note any environment that has **no** automated pipeline (manual deploy).

### Deploy commands
The actual command each pipeline runs to deploy, and the equivalent a dev runs locally if permitted (cite the script/target). Note who may deploy where (e.g. devs → sandbox only) and any required role/credential.

### Secrets & env in CI
How the pipeline obtains secrets (CI secret store, OIDC role assumption, fetched from a parameter store at deploy time). **Do not duplicate** the full secret inventory — if a configuration/secrets table already exists (see `cloud-architecture.md`), reference it and only note what is CI-specific (e.g. a token the pipeline reads for post-deploy tests).

### Quality gates
What must pass before a merge/deploy proceeds (required checks, coverage threshold, approvals, branch protection) — cite the workflow `needs`/`if` wiring or repo settings if visible.

## Rules

- Cite every claim to a workflow file + line/block.
- Describe the pipeline as it is; don't propose new stages or tools.
- Never print secret values; name the mechanism and source only.
- Reference the secrets table elsewhere rather than restating it — one source of truth.
- Flag drift honestly (a workflow that lints but never runs tests, a deploy with no gate) as an observation.
