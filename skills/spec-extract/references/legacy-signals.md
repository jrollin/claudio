> Reference for: Spec Extract
> Load when: Phase 1 (Discovery) and Phase 3 (Analysis) — recognizing legacy-specific patterns that hide business rules

# Legacy Code Signals

Legacy codebases hide business rules in ways that greenfield code does not. This guide teaches you to hunt for these patterns during discovery and analysis.

---

## 1. Dead Code That's Actually Live

**Pattern:** Feature flags permanently set to `true`, branches kept "just in case," commented-out code that was uncommented in a hotfix and never cleaned up.

**How to detect:**
- Search for feature flags, toggles, `if (true)`, `if (ENV['FEATURE_X'])`
- Check if the flag is ever set to `false` anywhere — if not, the branch IS the behavior
- Look for `TODO`, `HACK`, `FIXME` comments near conditional branches

**Why it matters:** The "dead" branch may be the only implementation of a critical rule. If someone deletes it during cleanup, the rule vanishes.

**Rule to extract:** Document the rule in the live branch. Flag the toggle in Open Questions: "Feature flag `FEATURE_X` is always on — is this permanent behavior or pending removal?"

---

## 2. Rules Spread Across Layers

**Pattern:** A single business rule enforced partially in the frontend (form validation), partially in the backend (controller/service), and partially in the database (CHECK constraint or trigger).

**How to detect:**
- When you find a validation in one layer, search for the same field name or error message in other layers
- Check DB migration files for CHECK constraints, NOT NULL, UNIQUE, and triggers
- Search for the same constant or threshold in frontend and backend code

**Why it matters:** Each layer may enforce a different version of the "same" rule. The most restrictive layer wins at runtime, but the intended rule may be in a different layer.

**Rule to extract:** Document all enforcement points as a single rule with multiple sources. Flag discrepancies: "Backend allows 100 characters but DB column is VARCHAR(80) — which is the intended limit?"

---

## 3. Temporal Strata (Same Rule, Multiple Generations)

**Pattern:** The same business rule reimplemented 2-3 times across code generations — an old version in a legacy module, a new version in a refactored service, sometimes a third in a migration shim. Only one is active.

**How to detect:**
- Search for the same domain concept in multiple directories (e.g., `lib/legacy/`, `src/v2/`, `app/services/`)
- Check routing or dependency injection to determine which implementation is actually called
- Look for class names with `Legacy`, `Old`, `V2`, `New` prefixes/suffixes

**Why it matters:** The "old" version may still be active for certain code paths. The "new" version may not be fully deployed. Extracting from the wrong one gives you a rule that doesn't match production behavior.

**Rule to extract:** Document which version is active (trace the call chain). Flag the duplicates in Open Questions: "Two implementations of discount calculation exist — `LegacyDiscountService` and `DiscountService`. Routing suggests `LegacyDiscountService` is still active for API v1 clients."

---

## 4. Comments That Contradict Code

**Pattern:** A comment says "discount is 10%" but the code applies 20%. In legacy code, comments rot faster than code.

**How to detect:**
- When reading a function, compare comments to the actual logic
- Pay special attention to comments with dates, ticket numbers, or author names — they're snapshots of past intent
- Watch for `// updated to...` or `// changed from...` comments that describe a different state

**Why it matters:** The code is the source of truth, but the comment may describe the *intended* rule. The divergence itself is a finding — it might indicate a bug or an undocumented policy change.

**Rule to extract:** Extract what the code does (not what the comment says). Add an Open Question: "Comment says X but code does Y — intentional change or bug? See `file:line`."

---

## 5. Config/Environment-Driven Rules

**Pattern:** Business rules parameterized through environment variables, database-stored config, YAML/JSON files, or admin panels. The code path exists but the actual thresholds, flags, or limits live outside the source.

**How to detect:**
- Search for `ENV`, `process.env`, `os.environ`, `Rails.application.config`, `Settings.`, `Config.get`
- Check for YAML/JSON/TOML config files with domain-meaningful keys (`max_retry_count`, `free_shipping_threshold`, `trial_days`)
- Search for database tables named `settings`, `config`, `feature_flags`, `parameters`
- Look for admin interfaces that modify behavior at runtime

**Why it matters:** The rule's existence is in the code, but its value is external. Extracting "discount is applied if total exceeds threshold" is incomplete — you need to know the threshold, even if it's `ENV['DISCOUNT_THRESHOLD']`.

**Rule to extract:** Document the rule with the config key as the value: "Free shipping if order total exceeds `FREE_SHIPPING_THRESHOLD` (env var, current value unknown from code alone)." Flag in Open Questions: "Actual value of `FREE_SHIPPING_THRESHOLD` must be checked in deployment config."

---

## 6. Middleware and Interceptor Rules

**Pattern:** Business constraints enforced in middleware, before-filters, decorators, or AOP aspects that run before the "main" code. Often invisible when reading the business logic in isolation.

**How to detect:**
- Check route definitions for middleware chains: `router.use(authMiddleware)`, `before_action :check_quota`
- Search for decorator/annotation patterns: `@Authorize`, `@RateLimit`, `@ValidateBody`
- Look at framework configuration for global filters or interceptors
- Check for aspect-oriented patterns (AOP) in Java/Spring codebases

**Why it matters:** These rules execute silently before the main logic. A function may appear to have no authorization check — but a middleware applied at the route level handles it. Missing these means missing constraints.

**Rule to extract:** Document the middleware-enforced rule with its source in the middleware file, and note which routes/controllers it applies to.

---

## 7. Database Constraints as Rules

**Pattern:** Business rules enforced at the database level through CHECK constraints, UNIQUE indexes, foreign keys, NOT NULL, triggers, or stored procedures.

**How to detect:**
- Read migration files (Rails migrations, Flyway, Liquibase, Alembic, raw SQL)
- Check for `CREATE TRIGGER`, `CHECK (...)`, `UNIQUE INDEX`, `NOT NULL` in schema files
- Search for stored procedures that enforce business logic
- Look for ORM model validations that mirror DB constraints (or don't — that's a finding)

**Why it matters:** Even if application code has no validation, the database may silently enforce the rule. These are often the oldest and most authoritative rules in the system.

**Rule to extract:** Document the constraint with its source in the migration or schema file. Note whether the application layer also enforces it (redundant but safe) or doesn't (single point of enforcement).

---

## 8. Error Messages as Rule Documentation

**Pattern:** User-facing error messages that describe business rules more clearly than any comment or variable name: `"You cannot place more than 3 orders per day"`, `"Trial period has expired"`.

**How to detect:**
- Grep for user-facing error strings, exception messages, flash messages
- Search for i18n/translation keys that describe constraints (`errors.order_limit_exceeded`)
- Check validation error formatters

**Why it matters:** Error messages are often written by product people or copywriters. They describe the rule in domain language — exactly what the rule catalog needs.

**Rule to extract:** Use the error message as evidence for the rule description. It often gives you the exact business language.

---

## Checklist: Legacy Discovery Pass

During Phase 1, after building the initial cluster via call-graph tracing, run this checklist:

- [ ] Search for feature flags and environment variables related to the concept
- [ ] Check migration files and DB schema for constraints on related tables
- [ ] Search for middleware/filters/decorators applied to related routes or controllers
- [ ] Look for config files (YAML, JSON, TOML) with keys related to the concept
- [ ] Search for the concept name in multiple directories to detect temporal strata
- [ ] Grep for user-facing error messages related to the concept

Any findings from this checklist should be added to the symbol cluster (Boundary layer if infrastructure, Core Logic if they encode rules).
