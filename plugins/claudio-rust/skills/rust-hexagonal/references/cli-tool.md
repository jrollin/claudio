# CLI Tool Slice (clap)

An end-to-end slice for a CLI: `notebook add "buy milk"` appends a note to a notebook stored on the filesystem. The clap command is a driving adapter; the filesystem store is a driven adapter; the use case is pure domain.

The same domain could later expose itself over HTTP or gRPC by adding another driving adapter — no domain changes needed.

## Layout

```text
crates/
├── domain/                 # entities, ports, use cases
├── driving/
│   └── cli/                # clap commands — calls into use cases
├── driven/
│   └── fs_store/           # FsNoteStore — implements NoteStore port
└── bootstrap/              # lib.rs wires it together; main.rs is a thin shim
```

## Domain

```rust
// crates/domain/src/entities.rs
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct NoteId(pub Uuid);

#[derive(Debug, Clone)]
pub struct Note {
    pub id: NoteId,
    pub body: String,
}

impl Note {
    pub fn new(body: String) -> Self {
        Self { id: NoteId(Uuid::new_v4()), body }
    }
}
```

```rust
// crates/domain/src/error.rs
#[derive(Debug, thiserror::Error)]
pub enum DomainError {
    #[error("note body must not be empty")]
    EmptyBody,
    #[error("storage failure: {0}")]
    Storage(String),
}
```

```rust
// crates/domain/src/ports.rs
use crate::entities::Note;
use crate::error::DomainError;

#[async_trait::async_trait]
pub trait NoteStore: Send + Sync {
    async fn append(&self, note: &Note) -> Result<(), DomainError>;
    async fn list(&self) -> Result<Vec<Note>, DomainError>;
}
```

```rust
// crates/domain/src/use_cases/add_note.rs
use crate::entities::{Note, NoteId};
use crate::error::DomainError;
use crate::ports::NoteStore;

pub struct AddNote<S: NoteStore> {
    store: S,
}

impl<S: NoteStore> AddNote<S> {
    pub fn new(store: S) -> Self { Self { store } }

    pub async fn execute(&self, body: String) -> Result<NoteId, DomainError> {
        if body.trim().is_empty() {
            return Err(DomainError::EmptyBody);
        }
        let note = Note::new(body);
        self.store.append(&note).await?;
        Ok(note.id)
    }
}
```

## Filesystem adapter

```rust
// crates/driven/fs_store/src/lib.rs
use std::path::PathBuf;

use domain::entities::{Note, NoteId};
use domain::error::DomainError;
use domain::ports::NoteStore;
use tokio::fs;
use tokio::io::AsyncWriteExt;

pub struct FsNoteStore {
    path: PathBuf,
}

impl FsNoteStore {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }
}

impl From<std::io::Error> for DomainError {
    fn from(e: std::io::Error) -> Self {
        DomainError::Storage(e.to_string())
    }
}

#[async_trait::async_trait]
impl NoteStore for FsNoteStore {
    async fn append(&self, note: &Note) -> Result<(), DomainError> {
        let mut f = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .await?;
        let line = format!("{}\t{}\n", note.id.0, note.body.replace('\n', " "));
        f.write_all(line.as_bytes()).await?;
        Ok(())
    }

    async fn list(&self) -> Result<Vec<Note>, DomainError> {
        let text = match fs::read_to_string(&self.path).await {
            Ok(t) => t,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
            Err(e) => return Err(e.into()),
        };
        text.lines()
            .map(|line| {
                let (id, body) = line.split_once('\t').ok_or_else(|| {
                    DomainError::Storage("malformed note line".into())
                })?;
                let id = uuid::Uuid::parse_str(id)
                    .map_err(|e| DomainError::Storage(format!("bad uuid: {e}")))?;
                Ok(Note { id: NoteId(id), body: body.to_owned() })
            })
            .collect()
    }
}
```

Notes:

- `tokio::fs` stays inside the adapter.
- File-not-found maps to "empty list," not an error — that's a policy choice the adapter owns.

## CLI adapter

```rust
// crates/driving/cli/src/lib.rs
use std::path::PathBuf;

use clap::{Parser, Subcommand};
use domain::ports::NoteStore;
use domain::use_cases::add_note::AddNote;

#[derive(Parser)]
#[command(name = "notebook", version)]
pub struct Cli {
    #[arg(long, env = "NOTEBOOK_PATH", default_value = "./notebook.tsv")]
    pub path: PathBuf,
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Subcommand)]
pub enum Command {
    Add { body: String },
    List,
}

pub async fn run<S: NoteStore>(store: S, command: Command) -> anyhow::Result<()> {
    match command {
        Command::Add { body } => {
            let uc = AddNote::new(store);
            let id = uc.execute(body).await?;
            println!("added {}", id.0);
        }
        Command::List => {
            for note in store.list().await? {
                println!("{}\t{}", note.id.0, note.body);
            }
        }
    }
    Ok(())
}
```

Notes:

- `clap` is confined to the CLI adapter.
- `run` is generic over `S: NoteStore`. Tests can pass an in-memory store; production passes `FsNoteStore`.
- The `List` branch calls the port directly because there's nothing for a use case to do (no invariants). If you find yourself adding logic, extract a `ListNotes` use case rather than letting it grow in the CLI handler.

## Bootstrap

Split into a library `run_cli` (the part you can test) and a thin binary shim (the part you can't).

```rust
// crates/bootstrap/src/lib.rs
use driving_cli::{Cli, run};
use driven_fs_store::FsNoteStore;

pub async fn run_cli(cli: Cli) -> anyhow::Result<()> {
    let store = FsNoteStore::new(cli.path);
    run(store, cli.command).await
}
```

```rust
// crates/bootstrap/src/main.rs
use clap::Parser;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    bootstrap::run_cli(driving_cli::Cli::parse()).await
}
```

```toml
# crates/bootstrap/Cargo.toml
[lib]
path = "src/lib.rs"

[[bin]]
name = "notebook"
path = "src/main.rs"
```

Integration tests in `crates/bootstrap/tests/` construct a `Cli` value directly (no process spawn) and call `run_cli` against a `tempdir`-backed `FsNoteStore`. Argv parsing stays in `main.rs` — the only thing the test can't reach — and is trivially correct.

## Tests

### Use case (in-memory port)

```rust
// crates/domain/src/use_cases/add_note.rs
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    #[derive(Default)]
    struct InMemoryNotes(Mutex<Vec<Note>>);

    #[async_trait::async_trait]
    impl NoteStore for InMemoryNotes {
        async fn append(&self, note: &Note) -> Result<(), DomainError> {
            self.0.lock().unwrap().push(note.clone());
            Ok(())
        }
        async fn list(&self) -> Result<Vec<Note>, DomainError> {
            Ok(self.0.lock().unwrap().clone())
        }
    }

    #[tokio::test]
    async fn adds_a_note() {
        let uc = AddNote::new(InMemoryNotes::default());
        let id = uc.execute("buy milk".into()).await.unwrap();
        let stored = uc.store.list().await.unwrap();
        assert_eq!(stored.len(), 1);
        assert_eq!(stored[0].id, id);
    }

    #[tokio::test]
    async fn rejects_empty_body() {
        let uc = AddNote::new(InMemoryNotes::default());
        let err = uc.execute("   ".into()).await.unwrap_err();
        assert!(matches!(err, DomainError::EmptyBody));
    }
}
```

### Adapter (real temp directory)

```rust
// crates/driven/fs_store/tests/integration.rs
use driven_fs_store::FsNoteStore;
use domain::entities::Note;
use domain::ports::NoteStore;

#[tokio::test]
async fn appends_and_lists_notes() {
    let dir = tempfile::tempdir().unwrap();
    let store = FsNoteStore::new(dir.path().join("notebook.tsv"));
    let note = Note::new("hello".into());
    store.append(&note).await.unwrap();

    let all = store.list().await.unwrap();
    assert_eq!(all.len(), 1);
    assert_eq!(all[0].id, note.id);
    assert_eq!(all[0].body, "hello");
}

#[tokio::test]
async fn empty_file_lists_nothing() {
    let dir = tempfile::tempdir().unwrap();
    let store = FsNoteStore::new(dir.path().join("missing.tsv"));
    assert!(store.list().await.unwrap().is_empty());
}
```

Real filesystem, real `tempfile::tempdir()`. No mocked `tokio::fs`.

## What stays out of the domain

- `clap` derives or types (`Parser`, `Subcommand`, `Args`)
- `std::path::PathBuf` (a CLI/filesystem concern — pass content into the domain, not paths)
- `tokio::fs` and `std::fs`
- Stdout/stderr formatting

If any of those appear in `crates/domain/`, move them to an adapter.
