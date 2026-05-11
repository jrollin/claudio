# HTTP Service Slice (axum)

An end-to-end slice for an HTTP API: `POST /users` accepts an email, creates a user, returns its ID. The HTTP handler is a driving adapter; the Postgres repository is a driven adapter; the use case is pure domain.

This shows how to keep `axum` types out of the domain even when HTTP is the primary interface.

## Layout

```text
crates/
├── domain/                 # entities, ports, use cases (same as generic-crud.md)
├── driving/
│   └── http/               # axum router and handlers — calls into use cases
├── driven/
│   └── postgres/           # PostgresUserRepository — implements domain port
└── bootstrap/              # lib.rs builds the wired app; main.rs is a thin shim
```

## HTTP adapter

```rust
// crates/driving/http/src/lib.rs
use std::sync::Arc;

use axum::{
    Json, Router,
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::post,
};
use domain::entities::Email;
use domain::error::DomainError;
use domain::ports::UserRepository;
use domain::use_cases::register_user::RegisterUser;
use serde::{Deserialize, Serialize};

#[derive(Clone)]
pub struct AppState<R: UserRepository + 'static> {
    pub register_user: Arc<RegisterUser<Arc<R>>>,
}

pub fn router<R: UserRepository + 'static>(state: AppState<R>) -> Router {
    Router::new()
        .route("/users", post(register_user_handler::<R>))
        .with_state(state)
}

#[derive(Deserialize)]
struct RegisterUserRequest {
    email: String,
}

#[derive(Serialize)]
struct RegisterUserResponse {
    id: String,
}

async fn register_user_handler<R: UserRepository + 'static>(
    State(state): State<AppState<R>>,
    Json(body): Json<RegisterUserRequest>,
) -> Result<(StatusCode, Json<RegisterUserResponse>), HttpError> {
    let email = Email::parse(&body.email).map_err(|m| HttpError::BadRequest(m.into()))?;
    let id = state.register_user.execute(email).await?;
    Ok((
        StatusCode::CREATED,
        Json(RegisterUserResponse { id: id.0.to_string() }),
    ))
}

// HTTP-layer error type. Converts domain errors into HTTP responses.
enum HttpError {
    BadRequest(String),
    Domain(DomainError),
}

impl From<DomainError> for HttpError {
    fn from(e: DomainError) -> Self {
        HttpError::Domain(e)
    }
}

impl IntoResponse for HttpError {
    fn into_response(self) -> Response {
        match self {
            HttpError::BadRequest(m) => (StatusCode::BAD_REQUEST, m).into_response(),
            HttpError::Domain(DomainError::EmailAlreadyTaken) => StatusCode::CONFLICT.into_response(),
            HttpError::Domain(DomainError::NotFound) => StatusCode::NOT_FOUND.into_response(),
            HttpError::Domain(DomainError::Storage(_)) => {
                // log internally — do NOT leak the storage error to the client
                StatusCode::INTERNAL_SERVER_ERROR.into_response()
            }
        }
    }
}
```

Notes:

- The handler takes `Json<RegisterUserRequest>` and produces `Json<RegisterUserResponse>`. These DTOs live in the HTTP adapter, not in the domain.
- `Email::parse` runs at the HTTP boundary. The domain never sees raw strings.
- `HttpError::Domain(DomainError::Storage(_))` returns 500 with **no detail**. Storage error text would leak SQL state or schema info to the client. Log it via `tracing::error!` elsewhere.
- The handler is generic over `R: UserRepository`. We could also use `Arc<dyn UserRepository>` for dyn dispatch — choose generics for zero-cost, `dyn` for simpler compile times.

## Bootstrap

Split into `build_app` (pure construction, returns a `Router`) and a thin binary that serves it. `build_app` is what integration tests call to exercise the fully wired stack without binding a port.

```rust
// crates/bootstrap/src/lib.rs
use std::sync::Arc;

use driving_http::{AppState, router};
use driven_postgres::PostgresUserRepository;
use axum::Router;
use domain::use_cases::register_user::RegisterUser;

pub async fn build_app() -> anyhow::Result<Router> {
    let pool = sqlx::PgPool::connect(&std::env::var("DATABASE_URL")?).await?;
    let users = Arc::new(PostgresUserRepository::new(pool));
    let register_user = Arc::new(RegisterUser::new(users.clone()));
    Ok(router(AppState { register_user }))
}
```

```rust
// crates/bootstrap/src/main.rs
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt::init();
    let app = bootstrap::build_app().await?;
    let listener = tokio::net::TcpListener::bind("0.0.0.0:3000").await?;
    axum::serve(listener, app).await?;
    Ok(())
}
```

```toml
# crates/bootstrap/Cargo.toml
[lib]
path = "src/lib.rs"

[[bin]]
name = "my-app"
path = "src/main.rs"
```

`lib.rs` is the only file that imports both adapters and the domain. `main.rs` only knows how to call `build_app()` and serve it.

End-to-end integration test using `build_app`:

```rust
// crates/bootstrap/tests/register_user_e2e.rs
use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;

#[tokio::test]
async fn register_user_returns_201() {
    // DATABASE_URL points at a testcontainers-managed Postgres
    let app = bootstrap::build_app().await.unwrap();
    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/users")
                .header("content-type", "application/json")
                .body(Body::from(r#"{"email":"alice@example.com"}"#))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::CREATED);
}
```

This is the integration test that's **impossible** when wiring lives in `main.rs`. It's the payoff for the split.

## Implementing `UserRepository` for `Arc<R>`

To inject `Arc<PostgresUserRepository>` into a use case that wants `R: UserRepository`, blanket-impl the trait for `Arc<T>` where `T: UserRepository`. Or use `Arc<dyn UserRepository>` and remove the generic from `RegisterUser`. Pick one.

Quick blanket impl (put it in the domain alongside the trait):

```rust
#[async_trait::async_trait]
impl<T: UserRepository> UserRepository for Arc<T> {
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError> {
        (**self).find_by_id(id).await
    }
    async fn find_by_email(&self, email: &Email) -> Result<Option<User>, DomainError> {
        (**self).find_by_email(email).await
    }
    async fn save(&self, user: &User) -> Result<(), DomainError> {
        (**self).save(user).await
    }
}
```

## HTTP integration test

```rust
// crates/driving/http/tests/register_user.rs
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use driving_http::{AppState, router};
use axum::body::Body;
use axum::http::{Request, StatusCode};
use domain::entities::{Email, User, UserId};
use domain::error::DomainError;
use domain::ports::UserRepository;
use domain::use_cases::register_user::RegisterUser;
use http_body_util::BodyExt;
use tower::ServiceExt;

#[derive(Default)]
struct InMemoryUsers(Mutex<HashMap<UserId, User>>);

#[async_trait::async_trait]
impl UserRepository for InMemoryUsers {
    async fn find_by_id(&self, id: UserId) -> Result<Option<User>, DomainError> {
        Ok(self.0.lock().unwrap().get(&id).cloned())
    }
    async fn find_by_email(&self, email: &Email) -> Result<Option<User>, DomainError> {
        Ok(self.0.lock().unwrap().values().find(|u| u.email() == email).cloned())
    }
    async fn save(&self, user: &User) -> Result<(), DomainError> {
        self.0.lock().unwrap().insert(user.id(), user.clone());
        Ok(())
    }
}

#[tokio::test]
async fn post_users_creates_and_returns_201() {
    let users = Arc::new(InMemoryUsers::default());
    let state = AppState { register_user: Arc::new(RegisterUser::new(users)) };
    let app = router(state);

    let response = app
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/users")
                .header("content-type", "application/json")
                .body(Body::from(r#"{"email":"alice@example.com"}"#))
                .unwrap(),
        )
        .await
        .unwrap();

    assert_eq!(response.status(), StatusCode::CREATED);
    let body = response.into_body().collect().await.unwrap().to_bytes();
    assert!(body.starts_with(b"{\"id\":\""));
}

#[tokio::test]
async fn post_users_with_duplicate_email_returns_409() {
    let users = Arc::new(InMemoryUsers::default());
    let state = AppState { register_user: Arc::new(RegisterUser::new(users)) };
    let app = router(state);

    let mk_req = || Request::builder()
        .method("POST")
        .uri("/users")
        .header("content-type", "application/json")
        .body(Body::from(r#"{"email":"alice@example.com"}"#))
        .unwrap();

    let _ = app.clone().oneshot(mk_req()).await.unwrap();
    let response = app.oneshot(mk_req()).await.unwrap();
    assert_eq!(response.status(), StatusCode::CONFLICT);
}
```

Notes:

- Tests cover the HTTP-to-domain wiring (status code mapping, JSON contract).
- The repository is in-memory. Postgres-specific behavior is tested in the postgres adapter's own integration tests (see `generic-crud.md`).
- This is the seam where ports and adapters pays off: swapping `InMemoryUsers` for `PostgresUserRepository` would change nothing in this test or in the handler.

## What stays out of the domain

- `axum::Json`, `axum::extract::State`, `axum::http::StatusCode`, `axum::Router`
- `serde::{Serialize, Deserialize}` derived on request/response DTOs
- `tracing` spans tied to HTTP requests
- Any notion of "headers", "status codes", or "JSON"

If any of those appear in `crates/domain/`, the architecture has leaked. Move them out.
