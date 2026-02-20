# TDD Reference: Rust

## Test Runner

```bash
cargo test test_name
cargo test --lib            # unit tests only
cargo test --test int_test  # specific integration test file
```

## Red-Green-Refactor Walkthrough

### Bug Fix: Empty email accepted

**RED**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_email() {
        let result = submit_form("");
        assert_eq!(result.unwrap_err(), "Email required");
    }
}
```

```bash
$ cargo test rejects_empty_email
FAILED: not yet implemented
```

**GREEN**

```rust
fn submit_form(email: &str) -> Result<(), &'static str> {
    if email.trim().is_empty() {
        return Err("Email required");
    }
    Ok(())
}
```

```bash
$ cargo test rejects_empty_email
ok
```

**REFACTOR** — Extract validation into a `Validator` trait if multiple fields need it.

### Feature: Retry with backoff

**RED**

```rust
#[test]
fn retries_failed_operations_3_times() {
    let attempts = std::cell::Cell::new(0);
    let operation = || {
        attempts.set(attempts.get() + 1);
        if attempts.get() < 3 {
            Err("fail")
        } else {
            Ok("success")
        }
    };

    let result = retry_operation(operation);

    assert_eq!(result.unwrap(), "success");
    assert_eq!(attempts.get(), 3);
}
```

**GREEN**

```rust
fn retry_operation<T, E, F>(mut f: F) -> Result<T, E>
where
    F: FnMut() -> Result<T, E>,
{
    let mut last_err = None;
    for _ in 0..3 {
        match f() {
            Ok(v) => return Ok(v),
            Err(e) => last_err = Some(e),
        }
    }
    Err(last_err.unwrap())
}
```

## Good vs Bad Tests

<Good>

```rust
#[test]
fn retries_failed_operations_3_times() {
    let attempts = std::cell::Cell::new(0);
    let operation = || {
        attempts.set(attempts.get() + 1);
        if attempts.get() < 3 { Err("fail") } else { Ok("success") }
    };

    let result = retry_operation(operation);

    assert_eq!(result.unwrap(), "success");
    assert_eq!(attempts.get(), 3);
}
```

Clear name, tests real behavior, one thing.

</Good>

<Bad>

```rust
#[test]
fn test_retry() {
    let mock = MockFn::new(vec![Err(""), Err(""), Ok("success")]);
    retry_operation(|| mock.next());
    assert_eq!(mock.call_count(), 3);
}
```

Vague name, tests mock not code.

</Bad>

## Good vs Bad Implementation

<Good>

```rust
fn retry_operation<T, E, F>(mut f: F) -> Result<T, E>
where
    F: FnMut() -> Result<T, E>,
{
    let mut last_err = None;
    for _ in 0..3 {
        match f() {
            Ok(v) => return Ok(v),
            Err(e) => last_err = Some(e),
        }
    }
    Err(last_err.unwrap())
}
```

Just enough to pass.

</Good>

<Bad>

```rust
fn retry_operation<T, E, F>(
    f: F,
    max_retries: Option<usize>,
    backoff: Option<BackoffStrategy>,
    on_retry: Option<Box<dyn Fn(usize)>>,
) -> Result<T, E>
where
    F: FnMut() -> Result<T, E>,
{
    // YAGNI
}
```

Over-engineered.

</Bad>

## Rust-Specific Patterns

### Testing Result/Option

```rust
#[test]
fn parses_valid_port() {
    assert_eq!(parse_port("8080"), Ok(8080));
}

#[test]
fn rejects_invalid_port() {
    assert!(parse_port("abc").is_err());
}

#[test]
fn returns_none_for_missing_key() {
    let config = Config::new();
    assert_eq!(config.get("missing"), None);
}
```

### Testing with async (tokio)

```rust
#[tokio::test]
async fn fetches_user_by_id() {
    let repo = UserRepo::new(test_db().await);
    let user = repo.find(42).await.unwrap();
    assert_eq!(user.name, "Alice");
}
```
