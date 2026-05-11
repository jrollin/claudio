# Generic CRUD: UserRepository

The textbook example. A `User` entity persisted through a `UserRepository` port, implemented twice: once against Postgres for production, once against an in-memory `HashMap` for tests.

This is the smallest possible end-to-end demo of ports and adapters in Rust.

## Layout

```text
crates/
├── domain/
│   ├── Cargo.toml          # async-trait, thiserror, uuid — NO sqlx
│   └── src/
│       ├── lib.rs
│       ├── entities.rs     # User, UserId, Email
│       ├── error.rs        # DomainError
│       ├── ports.rs        # UserRepository trait
│       └── use_cases/
│           ├── mod.rs
│           └── register_user.rs
├── driven/                 # adapters called by the domain via ports
│   └── postgres/
│       ├── Cargo.toml      # depends on domain + sqlx
│       └── src/lib.rs      # PostgresUserRepository (impl UserRepository)
└── bootstrap/
    ├── Cargo.toml          # depends on domain + driven adapters; has both [lib] and [[bin]] targets
    └── src/
        ├── lib.rs          # pub fn run() — wires adapters into use cases
        └── main.rs         # thin shim: calls bootstrap::run()
```

This example has no driving adapter (no HTTP or CLI). `main.rs` is the driving entrypoint here.

## Domain: entities

```rust
// crates/domain/src/entities.rs
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct UserId(pub Uuid);

impl UserId {
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Email(String);

impl Email {
    pub fn parse(raw: &str) -> Result<Self, &'static str> {
        if raw.contains('@') && raw.len() <= 254 {
            Ok(Self(raw.to_owned()))
        } else {
            Err("invalid email")
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone)]
pub struct User {
    id: UserId,
    email: Email,
}

impl User {
    pub fn new(email: Email) -> Self {
        Self { id: UserId::new(), email }
    }

    pub fn id(&self) -> UserId {
        self.id
    }

    pub fn email(&self) -> &Email {
        &self.email
    }
}
```

Notes:

- `UserId` and `Email` are newtypes. Raw `Uuid` and `String` never escape into use case signatures.
- `Email::parse` is the only constructor. It is impossible to build an invalid `Email`.

## Domain: error

```rust
// crates/domain/src/error.rs
#[derive(Debug, thiserror::Error)]
pub enum DomainError {
    #[error("user not found")]
    NotFound,
    #[error("email already taken")]
    EmailAlreadyTaken,
    #[error("storage failure: {0}")]
    Storage(String),
}
```

## Domain: port

```rust
// crates/domain/src/ports.rs
use crate::entities::{Email, User, UserId};
use crate::error::DomainError;

#[async_trait::async_trait]
pub trait UserRepository: Send + Sync {
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError>;
    async fn find_by_email(&self, email: &Email) -> Result<Option<User>, DomainError>;
    async fn save(&self, user: &User) -> Result<(), DomainError>;
}
```

## Domain: use case

```rust
// crates/domain/src/use_cases/register_user.rs
use crate::entities::{Email, User, UserId};
use crate::error::DomainError;
use crate::ports::UserRepository;

pub struct RegisterUser<R: UserRepository> {
    users: R,
}

impl<R: UserRepository> RegisterUser<R> {
    pub fn new(users: R) -> Self {
        Self { users }
    }

    pub async fn execute(&self, email: Email) -> Result<UserId, DomainError> {
        if self.users.find_by_email(&email).await?.is_some() {
            return Err(DomainError::EmailAlreadyTaken);
        }
        let user = User::new(email);
        self.users.save(&user).await?;
        Ok(user.id())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Mutex;

    #[derive(Default)]
    struct InMemoryUserRepo {
        by_id: Mutex<HashMap<UserId, User>>,
    }

    #[async_trait::async_trait]
    impl UserRepository for InMemoryUserRepo {
        async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError> {
            Ok(self.by_id.lock().unwrap().get(&id).cloned())
        }
        async fn find_by_email(&self, email: &Email) -> Result<Option<User>, DomainError> {
            Ok(self
                .by_id
                .lock()
                .unwrap()
                .values()
                .find(|u| u.email() == email)
                .cloned())
        }
        async fn save(&self, user: &User) -> Result<(), DomainError> {
            self.by_id.lock().unwrap().insert(user.id(), user.clone());
            Ok(())
        }
    }

    #[tokio::test]
    async fn registers_a_new_user() {
        let uc = RegisterUser::new(InMemoryUserRepo::default());
        let email = Email::parse("alice@example.com").unwrap();
        let id = uc.execute(email).await.unwrap();
        assert!(uc.users.find_by_id(id).await.unwrap().is_some());
    }

    #[tokio::test]
    async fn rejects_duplicate_email() {
        let uc = RegisterUser::new(InMemoryUserRepo::default());
        let email = Email::parse("alice@example.com").unwrap();
        uc.execute(email.clone()).await.unwrap();
        let err = uc.execute(email).await.unwrap_err();
        assert!(matches!(err, DomainError::EmailAlreadyTaken));
    }
}
```

Notes:

- Tests use an in-memory adapter. They never touch a database.
- Test names describe behavior, not implementation.
- `users` is `pub(crate)` inside the test module via direct field access — for cleanliness in real code, add an accessor or scope tests in a separate file.

## Adapter: Postgres

```rust
// crates/driven/postgres/src/lib.rs
use domain::entities::{Email, User, UserId};
use domain::error::DomainError;
use domain::ports::UserRepository;
use sqlx::PgPool;

pub struct PostgresUserRepository {
    pool: PgPool,
}

impl PostgresUserRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

impl From<sqlx::Error> for DomainError {
    fn from(e: sqlx::Error) -> Self {
        match e {
            sqlx::Error::RowNotFound => DomainError::NotFound,
            other => DomainError::Storage(other.to_string()),
        }
    }
}

#[async_trait::async_trait]
impl UserRepository for PostgresUserRepository {
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError> {
        let row = sqlx::query!("SELECT email FROM users WHERE id = $1", id.0)
            .fetch_optional(&self.pool)
            .await?;
        row.map(|r| {
            let email = Email::parse(&r.email)
                .map_err(|m| DomainError::Storage(format!("invalid email in db: {m}")))?;
            Ok(User::new_with_id(id, email))
        })
        .transpose()
    }

    async fn find_by_email(&self, email: &Email) -> Result<Option<User>, DomainError> {
        let row = sqlx::query!("SELECT id FROM users WHERE email = $1", email.as_str())
            .fetch_optional(&self.pool)
            .await?;
        row.map(|r| {
            Ok(User::new_with_id(UserId(r.id), email.clone()))
        })
        .transpose()
    }

    async fn save(&self, user: &User) -> Result<(), DomainError> {
        sqlx::query!(
            "INSERT INTO users (id, email) VALUES ($1, $2)",
            user.id().0,
            user.email().as_str(),
        )
        .execute(&self.pool)
        .await?;
        Ok(())
    }
}
```

Notes:

- `sqlx` lives only in this crate. Domain has zero knowledge of it.
- `From<sqlx::Error> for DomainError` converts at the boundary. The trait signature returns `DomainError`, not `sqlx::Error`.
- A real codebase needs a `User::new_with_id` reconstructor to rebuild entities from storage without going through the public `User::new` constructor that generates a fresh ID. Since the postgres adapter lives in a separate crate, this constructor must be `pub` (not `pub(crate)`). Mark it `#[doc(hidden)]` and document that it is for persistence adapters only.

## Bootstrap

Split into a library function (`run`) and a thin binary shim. The library is what integration tests call; the binary is what Cargo runs.

```rust
// crates/bootstrap/src/lib.rs
use driven_postgres::PostgresUserRepository;
use domain::entities::Email;
use domain::use_cases::register_user::RegisterUser;

pub async fn run() -> anyhow::Result<()> {
    let pool = sqlx::PgPool::connect(&std::env::var("DATABASE_URL")?).await?;
    let users = PostgresUserRepository::new(pool);
    let register = RegisterUser::new(users);

    let raw = std::env::var("REGISTER_EMAIL")?;
    let email = Email::parse(&raw).map_err(|m| anyhow::anyhow!(m))?;
    let id = register.execute(email).await?;
    println!("registered {id:?}");
    Ok(())
}
```

```rust
// crates/bootstrap/src/main.rs
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    bootstrap::run().await
}
```

The bootstrap crate's `Cargo.toml`:

```toml
[package]
name = "bootstrap"
edition = "2021"

[lib]
path = "src/lib.rs"

[[bin]]
name = "my-app"
path = "src/main.rs"
```

`lib.rs` is the only place that:

- imports both the adapter and the use case
- uses `anyhow::Result` (the binary boundary)

Per iron rule 5, `unwrap()` / `expect()` is forbidden everywhere except inside `fn main()` itself (for startup invariants like `parse()` on a hardcoded literal) and tests. In `lib.rs`, propagate with `?`.

`main.rs` stays trivially small so the only untestable code (the `#[tokio::main]` entry) is also the smallest.

## Integration test against real Postgres

```rust
// crates/driven/postgres/tests/repository.rs
use driven_postgres::PostgresUserRepository;
use domain::entities::Email;
use domain::ports::UserRepository;
use testcontainers::runners::AsyncRunner;
use testcontainers_modules::postgres::Postgres;

#[tokio::test]
async fn persists_and_retrieves_a_user() {
    let pg = Postgres::default().start().await.unwrap();
    let url = format!(
        "postgres://postgres:postgres@127.0.0.1:{}/postgres",
        pg.get_host_port_ipv4(5432).await.unwrap()
    );
    let pool = sqlx::PgPool::connect(&url).await.unwrap();
    sqlx::migrate!("./migrations").run(&pool).await.unwrap();

    let repo = PostgresUserRepository::new(pool);
    let email = Email::parse("alice@example.com").unwrap();
    let user = domain::entities::User::new(email.clone());
    repo.save(&user).await.unwrap();

    let found = repo.find_by_email(&email).await.unwrap();
    assert!(found.is_some());
}
```

Real Postgres in a container — no SQL mocks, no surprises in production.
