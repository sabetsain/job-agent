# Project Agent Guidelines

## Intent as a Living Source of Truth

- `docs/INTENT.md` is the source of truth for project intent, scope, principles, and workflows.
- `docs/INTENT.md` is a **living document**, not a frozen specification.
- During ideation, spec planning, or implementation, if a proposed change or existing spec conflicts with `docs/INTENT.md`, **surface the conflict explicitly** and resolve it with the user before proceeding.
- Resolution may mean either adjusting the spec/design to match `docs/INTENT.md`, or updating `docs/INTENT.md` to reflect evolved intent. Keep both aligned.

## Subagent Isolation & Git Workflow

- Subagents performing code edits or implementation work MUST run in isolated git worktrees / branched workspaces (`Workspace: "share"` or `"branch"`), never editing the parent working tree directly.
- Commit frequently per feature or logical unit with clear conventional commit messages (`feat(...)`, `test(...)`, `chore(...)`).
- Verify tests pass before merging subagent branches cleanly back into `main`.

## Session Handoff

- Latest session handoff document: `/Users/sebastianmcconnell/.gemini/handoffs/job-agent-schemas-and-ingestion-handoff.md`
