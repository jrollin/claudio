# Security Posture

An onboarding deliverable: where this repo's trust boundaries are and how it defends them, so a new dev knows what not to break. Describe what exists and cite it — this is a map, not an audit. State an absence as a neutral fact ("there is no input validation at the HTTP boundary"), but do not rank findings, score risk, or propose fixes; a security review is a separate task. Two phrasings that turn a map into an audit — avoid both: framing a fact as a "gap/risk" ("⚠️ log retention is too short"), and soft suggestions ("worth confirming…", "you should verify…", "make sure…"). If something can't be determined from the code, write "not determinable from the repo" — never "you should check it."

## Method

1. Read security-relevant config first: auth middleware, `.env.example`, CI security steps, dependency manifests, IaC IAM blocks. Then confirm against code.
2. Trace one request from the outside in: where is it authenticated, authorized, validated, and where does it touch a secret or a data store? That path is the trust boundary.
3. Never print secret values. Names, sources, and handling only.

## Required Output

Cover each dimension that applies; omit (and say so) the ones that genuinely don't.

### Authentication
How callers prove identity at the entry point: session, JWT, API key, OAuth/OIDC, mTLS, signed requests, an upstream authorizer (e.g. API Gateway authorizer, gateway/proxy). Cite the middleware/guard/authorizer. Note unauthenticated/public routes explicitly.

### Authorization
How allowed actions are decided after authentication: RBAC/ABAC, per-route guards, row/tenant scoping, IAM policies for service-to-service. Cite where the check lives. Flag any route that authenticates but never authorizes.

### Secrets & configuration
Where secrets come from and how they reach the code: env vars, a secrets manager (Secrets Manager / Vault / Key Vault), a parameter store, mounted files. Note rotation if declared. Confirm secrets are **not** committed: check for `.env` in `.gitignore`, absence of keys/tokens in tracked files, presence of a `.env.example` with placeholders. Cite. Never reproduce a value.

### Input validation & boundaries
Where untrusted input is validated/sanitized at system boundaries (request schemas, query/body validators, type guards). Note the query style for data stores — parameterized vs string-interpolated (SQL/NoSQL injection surface). Cite a validator and a query site.

### Transport & data protection
TLS/HTTPS enforcement, encryption at rest (DB/bucket/queue), PII handling and what is/ isn't logged. Cite the config (cert setup, bucket encryption, log redaction rules).

### Dependencies & supply chain
Lockfile present? Automated vuln scanning or dependency updates in CI (audit step, Dependabot/Renovate, SCA)? Private registry auth required? Cite the CI step or config file.

### Service-to-service & cloud IAM (cloud repos)
For cloud-native repos: the execution role's granted actions (least-privilege vs wildcard), network exposure (public endpoint, VPC, security-group egress), and how it authenticates to other internal services (shared key, signed, mTLS). Cite the IaC. Cross-reference `cloud-architecture.md` rather than repeating it.

## Rules

- Map, don't audit: report what exists with citations; do not score, rank, or recommend fixes.
- Never print secret/credential/token values — names, sources, and handling only.
- A clear absence (no authz on a write route, secrets in a tracked file, string-interpolated queries) is worth stating plainly as an observation, with its file cited.
- Confirm against code; don't infer a control exists because a doc or dependency name suggests it.
- Cite every claim — same standard as the rest of onboarding.
