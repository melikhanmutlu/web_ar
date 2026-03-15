---
description: Memory Bank system. Scans project, captures patterns, decisions, and active context for cross-session persistence.
---

# /remember - Memory Bank System

$ARGUMENTS

---

## Purpose

This command creates or updates the project's Memory Bank — a set of persistent context files that survive across sessions. Claude reads these at session start to avoid re-discovering the same information.

---

## Sub-commands

```
/remember              - Full scan: create/update all memory files
/remember context      - Update only active context (what's being worked on now)
/remember patterns     - Update only detected patterns and conventions
/remember decisions    - Update only architecture decisions
/remember issues       - Update only troubleshooting log
/remember status       - Show current memory bank status
```

---

## Behavior

When `/remember` is triggered:

### 1. Scan Project

Analyze the project to understand:
- **Tech stack**: package.json, requirements.txt, go.mod, Cargo.toml, etc.
- **Architecture**: folder structure, naming conventions, file organization
- **Patterns**: recurring code patterns, import styles, state management approach
- **Recent activity**: git log, recent changes, current branch

### 2. Create/Update Memory Files

Write findings to `.agent/.claude/memory/`:

| File | Content |
|------|---------|
| `MEMORY-activeContext.md` | Current work: branch, recent commits, active feature, blockers |
| `MEMORY-patterns.md` | Numbered patterns: naming conventions, file structure, code style, component patterns |
| `MEMORY-decisions.md` | Architecture Decision Records (ADR): each decision with rationale and date |
| `MEMORY-troubleshooting.md` | Solved issues: problem, root cause, solution, date |

### 3. Preserve History

**CRITICAL RULES:**
- NEVER delete existing entries — only append or update
- Preserve all historical records (ADRs, past patterns, solved issues)
- When updating, add new entries with current date
- Mark outdated patterns as `[DEPRECATED]` instead of removing

---

## Key Principles

- **Append-only** — never delete history, only add
- **Concise** — keep entries short, no verbose prose
- **Factual** — record what happened, not speculation
- **Actionable** — patterns and solutions should be directly reusable
