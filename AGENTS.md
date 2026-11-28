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

# General Instructions

- **Trigger:** You need to explain a bug, issue, implementation, or idea to the user.
  - **Action:** Add abstract, high-level context to cushion your explanation.

- **Trigger:** Once the intent of a session is clear and there is a relevant handoff document in the `.handoffs/` directory at the project root.
  - **Action:** Read the handoff. Always update the existing handoff document instead of making a new one.

- **Trigger:** Uncertainty about user query.
  - **Action:** Ask clarifying questions.

- **Trigger:** Need a container environment.
  - **Action:** Check for active podman before any other tooling.

- **Trigger:** Managing local branches or version control with git.
  - **Action:** Use gh stack for local branch work: init, add, submit, sync, rebase, view, up/down. Refer to /create-pr skill as needed.

- **Trigger:** Starting work on a clean project (or any workspace without an initialized OpenSpec setup).
  - **Action:** Check silently whether the `openspec` CLI is installed (`openspec --version`) and whether the project has OpenSpec initialized (`openspec/` at the project root or a configured store in `openspec/config.yaml`). **Never prompt the user.** If `openspec` is not installed, install it non-interactively (`npm install -g @fission-ai/openspec@latest`, or run via `npx @fission-ai/openspec@latest`). If OpenSpec is not initialized in the project, run `openspec init --scope project --tools antigravity --force` so both `openspec/` and project-scoped `.agents/skills/` are provisioned cleanly without interactive prompts — including in remote Antigravity sessions. OpenSpec skills may also live in a dedicated `openspec/` or `.agents/skills/` directory.
