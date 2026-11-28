---
name: create-pr
description: "Create a PR based on the current branch or worktree"
---

## Prerequisites
- Confirm `gh` is available and authenticated (`gh auth status`) via Antigravity's connected GitHub plugin. Do **not** run interactive `gh auth login` in remote Antigravity VMs — if unauthenticated or expired, prompt the user to connect/reconnect the GitHub plugin (`<plugin-card catalog-id="github"></plugin-card>`).
- For local stack work, check if `gh-stack` is installed (`gh extension list`); if missing and permitted, install with `gh extension install github/gh-stack` (needs `gh` 2.0+ and Git 2.36+).
- For REST calls, send `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2026-03-10`.
- The caller needs write access to the repository.
- After creating or updating a PR, bookmark the PR URL as a `UserFacing: true` `.url.json` artifact in Antigravity so it surfaces directly for review.

## Create a diff breakdown table

- Give a size breakdown table per PR, and focus on the areas that contribute most to the size or that are most impactful to the PR.
  - Table columns: Area | Lines | What it is. Group files by purpose (tests, the
    new component, manifests, wiring, docs/spec), not one row per file.
  - Get counts from `gh api repos/{owner}/{repo}/pulls/{n}/files` and per-commit
    stats, so you can say which commit carries the weight.
  - Call out lines that inflate the count without adding logic: code moved from another file (match + and − across files), tests and fixtures, docs.
  - Say which unrelated changes are bundled in, and how the PR could be split.


## Ensure remote stack management

- Use the REST Stacks API for remote work with no local checkout.
- `GET /repos/{owner}/{repo}/stacks` lists stacks. It can filter by a PR number.
- `POST /repos/{owner}/{repo}/stacks` creates a stack from pull_requests, an ordered array of PR numbers from bottom to top. Each PR's base ref must equal the previous PR's head ref.
- `GET /repos/{owner}/{repo}/stacks/{stack_number}` fetches one stack.
- `POST /repos/{owner}/{repo}/stacks/{stack_number}/add` appends PRs at the top. The first new PR's base must match the current top's head.
- `POST /repos/{owner}/{repo}/stacks/{stack_number}/unstack` removes unmerged PRs. It returns 200 if PRs remain, or 204 if the stack is dissolved.
- Handle errors: 404 (not found), 409 (another request is modifying the stack, so retry), 422 (invalid stack).

## Never exceed 150 lines per PR

- Aim to keep each PR under 150 lines of changes to make reviews manageable.
- If a PR exceeds this limit, consider splitting it into smaller, focused PRs.
- Use the diff breakdown table to identify large areas and potential split points.
- Prioritize splitting changes that touch multiple unrelated areas to keep each PR focused and reviewable.
- If a PR cannot be split to under 150 lines, provide a clear explanation and raise the issue to a human reviewer.