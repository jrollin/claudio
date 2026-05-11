# OpenAPI with utoipa (axum)

Same `POST /users` slice as `http-service.md`, now with a fully generated OpenAPI document and a browseable Swagger UI.

The architectural rule: **every utoipa annotation lives in the HTTP adapter.** The domain stays free of `ToSchema`, `utoipa::path`, and `serde` derives. DTOs in the HTTP adapter mirror domain types and carry all the OpenAPI metadata.

## Dependencies

In `crates/driving/http/Cargo.toml`:

```toml
[dependencies]
axum = "0.7"
serde = { version = "1", features = ["derive"] }
utoipa = { version = "5", features = ["axum_extras"] }
utoipa-axum = "0.1"
utoipa-swagger-ui = { version = "8", features = ["axum"] }
async-trait = "0.1"
domain = { path = "../../domain" }
```

The domain crate adds nothing. Check its `Cargo.toml` — no `utoipa`, no `serde`. The domain stays pristine.

## Layout

```text
crates/
├── domain/                          # entities, ports, use cases (unchanged)
├── driving/
│   └── http/                        # axum + utoipa annotations live here
│       ├── Cargo.toml
│       └── src/
│           ├── lib.rs               # router + ApiDoc + swagger mount
│           ├── dto.rs               # ToSchema-annotated DTOs
│           ├── error.rs             # HttpError + IntoResponse
│           └── handlers/
│               └── register_user.rs # #[utoipa::path] handler
├── driven/
│   └── postgres/                    # unchanged
└── bootstrap/                       # lib.rs (build_app) + main.rs (5-line shim)
```

## DTOs with `ToSchema`

```rust
// crates/driving/http/src/dto.rs
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

#[derive(Debug, Deserialize, ToSchema)]
pub struct RegisterUserRequest {
    /// User email address (RFC 5322).
    #[schema(example = "alice@example.com")]
    pub email: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct RegisterUserResponse {
    /// Newly created user ID.
    #[schema(example = "550e8400-e29b-41d4-a716-446655440000")]
    pub id: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ErrorBody {
    /// Stable machine-readable error code.
    #[schema(example = "email_already_taken")]
    pub code: String,
    /// Human-readable summary. May be omitted in production.
    #[schema(example = "An account with that email already exists.")]
    pub message: String,
}
```

Notes:

- DTOs are HTTP-shaped, not domain-shaped. The domain `Email` newtype becomes a plain `String` here, validated on the way in.
- `#[schema(example = ...)]` produces nicer Swagger output.
- `ErrorBody` is the canonical error shape. Mapping happens in `HttpError::into_response`.

## Error mapping

```rust
// crates/driving/http/src/error.rs
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use domain::error::DomainError;

use crate::dto::ErrorBody;

pub enum HttpError {
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
        let (status, code, message) = match self {
            HttpError::BadRequest(m) => (StatusCode::BAD_REQUEST, "bad_request", m),
            HttpError::Domain(DomainError::EmailAlreadyTaken) => (
                StatusCode::CONFLICT,
                "email_already_taken",
                "An account with that email already exists.".to_owned(),
            ),
            HttpError::Domain(DomainError::NotFound) => (
                StatusCode::NOT_FOUND,
                "not_found",
                "Resource not found.".to_owned(),
            ),
            HttpError::Domain(DomainError::Storage(_)) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
                "An internal error occurred.".to_owned(),
            ),
        };
        (
            status,
            Json(ErrorBody { code: code.to_owned(), message }),
        )
            .into_response()
    }
}
```

`Storage` errors collapse to a generic message: never leak SQL or schema details to the client.

## Handler with `#[utoipa::path]`

```rust
// crates/driving/http/src/handlers/register_user.rs
use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use domain::entities::Email;
use domain::ports::UserRepository;
use domain::use_cases::register_user::RegisterUser;

use crate::dto::{ErrorBody, RegisterUserRequest, RegisterUserResponse};
use crate::error::HttpError;
use crate::AppState;

/// Register a new user.
///
/// Creates a user identified by the given email. The email must not already exist.
#[utoipa::path(
    post,
    path = "/users",
    tag = "users",
    request_body = RegisterUserRequest,
    responses(
        (status = 201, description = "User created", body = RegisterUserResponse),
        (status = 400, description = "Invalid email", body = ErrorBody),
        (status = 409, description = "Email already taken", body = ErrorBody),
        (status = 500, description = "Internal server error", body = ErrorBody),
    )
)]
pub async fn register_user<R: UserRepository + 'static>(
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
```

The doc comment becomes the OpenAPI `summary` and `description`. The macro arguments produce the path, request body, and response schemas.

## ApiDoc aggregation + router

```rust
// crates/driving/http/src/lib.rs
use std::sync::Arc;

use axum::Router;
use domain::ports::UserRepository;
use domain::use_cases::register_user::RegisterUser;
use utoipa::OpenApi;
use utoipa_axum::router::OpenApiRouter;
use utoipa_axum::routes;
use utoipa_swagger_ui::SwaggerUi;

mod dto;
mod error;
mod handlers;

#[derive(Clone)]
pub struct AppState<R: UserRepository + 'static> {
    pub register_user: Arc<RegisterUser<Arc<R>>>,
}

#[derive(OpenApi)]
#[openapi(
    info(
        title = "Users API",
        version = "0.1.0",
        description = "Hexagonal Rust example service."
    ),
    tags(
        (name = "users", description = "User registration and lookup")
    ),
    components(schemas(
        dto::RegisterUserRequest,
        dto::RegisterUserResponse,
        dto::ErrorBody,
    ))
)]
pub struct ApiDoc;

pub fn router<R: UserRepository + 'static>(state: AppState<R>) -> Router {
    let (api_router, api) = OpenApiRouter::with_openapi(ApiDoc::openapi())
        .routes(routes!(handlers::register_user::register_user::<R>))
        .with_state(state)
        .split_for_parts();

    api_router
        .merge(SwaggerUi::new("/docs").url("/api-doc/openapi.json", api))
}
```

Three things wired here:

1. `OpenApiRouter` collects route metadata from `#[utoipa::path]` automatically.
2. `split_for_parts()` separates the axum `Router` from the assembled `OpenApi`.
3. `SwaggerUi::new("/docs")` mounts Swagger UI at `/docs` and serves the raw spec at `/api-doc/openapi.json`.

After `bootstrap` runs the service:

- `GET /api-doc/openapi.json` returns the OpenAPI 3.1 JSON document.
- `GET /docs` renders Swagger UI.

## Bootstrap (lib + thin main)

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
    println!("Swagger UI: http://localhost:3000/docs");
    axum::serve(listener, app).await?;
    Ok(())
}
```

## Test: spec is generated and stable

```rust
// crates/driving/http/tests/openapi.rs
use driving_http::ApiDoc;
use utoipa::OpenApi;

#[test]
fn openapi_spec_contains_register_user() {
    let spec = ApiDoc::openapi();
    let paths = spec.paths.paths;
    let item = paths.get("/users").expect("/users path missing");
    assert!(item.post.is_some(), "POST /users not declared");
}

#[test]
fn openapi_spec_lists_error_body_schema() {
    let json = serde_json::to_string(&ApiDoc::openapi()).unwrap();
    assert!(json.contains("\"ErrorBody\""), "ErrorBody schema not exposed");
}
```

Snapshot the JSON (with `insta` or similar) once the API is stable so accidental shape changes break tests instead of clients.

## Architectural payoff

Look at the dependency direction:

- `domain` depends on nothing infrastructural. `cargo tree -p domain` shows no `utoipa`, no `axum`, no `serde`.
- `driving_http` depends on `domain` + the HTTP/utoipa stack.
- The use case (`RegisterUser`) doesn't know an OpenAPI document exists.

You could:

- Add a gRPC adapter with its own protobuf schemas — domain unaffected.
- Swap utoipa for `aide` — only `driving_http` changes.
- Generate the spec at CI time and publish it to a docs portal — no production runtime cost.

## What stays out of the domain

- `utoipa::ToSchema`, `utoipa::OpenApi`, `#[utoipa::path]`
- `serde::Serialize` / `Deserialize` derives
- HTTP-shaped DTOs (`RegisterUserRequest`, `ErrorBody`, …)
- Any notion of "OpenAPI", "tags", or "examples"

If any of these appear in `crates/domain/`, the architecture has leaked. Move them to the HTTP adapter.
