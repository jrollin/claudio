> Reference for: Spec Implement
> Load when: Writing or running Verify commands — need language-specific patterns

# Verify Commands by Language

Verify commands must exit with code 0 on success, non-zero on failure. This reference shows idiomatic patterns per ecosystem.

---

## JavaScript / TypeScript

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| Jest | `npx jest --testPathPattern "auth/service"` | `npx jest --testPathPattern "auth/routes"` | `npx jest --config jest.e2e.config.ts` |
| Vitest | `npx vitest run src/auth/service.test.ts` | `npx vitest run src/auth/routes.test.ts` | `npx vitest run --config vitest.e2e.config.ts` |
| Mocha | `npx mocha --grep "AuthService"` | `npx mocha --grep "POST /auth/login"` | — |
| Node test runner | `node --test --test-name-pattern "AuthService" src/auth/` | `node --test src/auth/routes.test.ts` | — |
| Playwright | — | — | `npx playwright test auth.spec.ts` |
| Cypress | — | — | `npx cypress run --spec "cypress/e2e/auth.cy.ts"` |

### Common Patterns

```markdown
- **Verify**: `npx vitest run src/auth/service.test.ts`
- **Verify**: `npx jest --testPathPattern "auth/service" --no-coverage`
- **Verify**: `npm run test -- --grep "AuthService"`
```

### Migration + Schema

```markdown
- **Verify**: `npx prisma migrate deploy && npx vitest run src/db/schema.test.ts`
- **Verify**: `npx knex migrate:latest && npx jest --testPathPattern "schema"`
```

### Lint / Type Check (complement, not substitute)

```markdown
- **Verify**: `npx vitest run src/auth/ && npx tsc --noEmit`
```

Type check alone is never a sufficient verify — always pair with a behavioral test.

---

## Python

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| pytest | `pytest tests/auth/test_service.py -v` | `pytest tests/auth/test_routes.py -v` | `pytest tests/e2e/test_auth_flow.py -v` |
| unittest | `python -m pytest tests/auth/test_service.py` | — | — |

### Common Patterns

```markdown
- **Verify**: `pytest tests/auth/test_service.py -v`
- **Verify**: `pytest tests/auth/ -k "test_lockout" -v`
- **Verify**: `pytest tests/auth/test_routes.py -v --tb=short`
```

### Migration + Schema

```markdown
- **Verify**: `alembic upgrade head && pytest tests/db/test_schema.py -v`
- **Verify**: `python manage.py migrate && pytest tests/models/ -v`
```

### With Coverage Threshold

```markdown
- **Verify**: `pytest tests/auth/ --cov=src/auth --cov-fail-under=80`
```

---

## Rust

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| cargo test | `cargo test auth::service` | `cargo test --test auth_routes` | `cargo test --test e2e_auth` |

### Common Patterns

```markdown
- **Verify**: `cargo test auth::service`
- **Verify**: `cargo test --test auth_integration`
- **Verify**: `cargo test lockout -- --nocapture`
```

### With Feature Flags

```markdown
- **Verify**: `cargo test --features "auth" auth::service`
```

### Lint Complement

```markdown
- **Verify**: `cargo test auth::service && cargo clippy -- -D warnings`
```

---

## Go

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| go test | `go test ./internal/auth/ -run TestService` | `go test ./internal/auth/ -run TestRoutes -tags=integration` | `go test ./tests/e2e/ -run TestAuthFlow -tags=e2e` |

### Common Patterns

```markdown
- **Verify**: `go test ./internal/auth/ -run TestService -v`
- **Verify**: `go test ./internal/auth/ -run TestLockout -v`
- **Verify**: `go test ./internal/auth/... -v`
```

### With Race Detection

```markdown
- **Verify**: `go test -race ./internal/auth/ -run TestService`
```

---

## Dart / Flutter

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| dart test | `dart test test/auth/service_test.dart` | `dart test test/auth/routes_test.dart` | — |
| flutter test | `flutter test test/auth/service_test.dart` | `flutter test integration_test/auth_test.dart` | `flutter test integration_test/app_test.dart` |

### Common Patterns

```markdown
- **Verify**: `dart test test/auth/service_test.dart`
- **Verify**: `flutter test test/auth/service_test.dart`
- **Verify**: `flutter test --name "lockout" test/auth/`
```

### Integration with Device

```markdown
- **Verify**: `flutter test integration_test/auth_test.dart -d chrome`
```

---

## Java / Kotlin

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| Maven | `mvn test -pl auth -Dtest="AuthServiceTest"` | `mvn verify -pl auth -Dit.test="AuthRoutesIT"` | `mvn verify -pl e2e` |
| Gradle | `./gradlew :auth:test --tests "AuthServiceTest"` | `./gradlew :auth:integrationTest --tests "AuthRoutesIT"` | `./gradlew :e2e:test` |

### Common Patterns

```markdown
- **Verify**: `./gradlew :auth:test --tests "AuthServiceTest"`
- **Verify**: `mvn test -pl auth -Dtest="AuthServiceTest"`
```

---

## Elixir

### Test Runners

| Runner | Unit | Integration | E2E |
|--------|------|-------------|-----|
| mix test | `mix test test/auth/service_test.exs` | `mix test test/auth/routes_test.exs` | `mix test test/e2e/auth_test.exs` |

### Common Patterns

```markdown
- **Verify**: `mix test test/auth/service_test.exs`
- **Verify**: `mix test --only auth`
```

---

## Shell / CLI Tools

For tasks that don't have a test framework (scripts, migrations, config):

```markdown
- **Verify**: `./scripts/verify-migration.sh && echo "OK"`
- **Verify**: `bash -c 'source .env.test && ./scripts/health-check.sh'`
```

Always prefer a test runner over a custom script. Custom scripts must still exit 0 on success, non-zero on failure.

---

## Detecting the Project's Ecosystem

Identify the ecosystem during Initialize (Step 1) to understand Verify commands throughout implementation:

| File | Ecosystem | Likely Test Runner |
|------|-----------|--------------------|
| `package.json` | JS/TS | Check `scripts.test` — jest, vitest, mocha, or node --test |
| `pyproject.toml` / `setup.py` | Python | pytest (check `[tool.pytest]`) |
| `Cargo.toml` | Rust | cargo test |
| `go.mod` | Go | go test |
| `pubspec.yaml` | Dart/Flutter | dart test / flutter test |
| `pom.xml` | Java/Kotlin (Maven) | mvn test |
| `build.gradle` / `build.gradle.kts` | Java/Kotlin (Gradle) | ./gradlew test |
| `mix.exs` | Elixir | mix test |
