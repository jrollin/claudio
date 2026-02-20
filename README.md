# Claudio

Claude Code plugin for spec-driven development.

## Skills

| Skill | Description |
|-------|-------------|
| `spec-create` | Create feature specifications (Requirements → Design → Tasks) |
| `spec-impl` | Implement tasks from a completed specification |

## Install

### From Git repository

```bash
# Add marketplace
/plugin marketplace add git@github.com:jrollin/claudio.git

# Install the plugin
/plugin install claudio
```

### Local development

```bash
claude --plugin-dir /path/to/claudio
```

## Usage

```
/claudio:spec-create <feature-name> [description]
/claudio:spec-impl <feature-name>
```

Typical workflow:

1. `/claudio:spec-create my-feature` — generates `docs/features/my-feature/{requirements,design,tasks}.md`
2. `/claudio:spec-impl my-feature` — implements tasks one-by-one from the spec
