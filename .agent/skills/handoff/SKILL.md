---
name: handoff
description: Compact the current conversation into a project-scoped handoff document in .handoffs/ for a fresh Gemini/Antigravity session to pick up.
argument-hint: "What will the next session be used for?"
---

Write a handoff document summarising the current conversation so a fresh Gemini / Antigravity agent session can seamlessly continue the work.

* Save the handoff document inside the `.handoffs/` directory at the root of the current project workspace (create `.handoffs/` if it does not exist).
* Check `.handoffs/` first — if a relevant handoff document already exists for this project or workstream, update it in place rather than creating a duplicate file.
* Include a **Suggested skills** section listing the skills the next agent session should invoke.
* Do not duplicate content already captured in other project files or artifacts (PRDs, plans, ADRs, OpenSpec changes, issues, commits, diffs). Reference them by workspace-relative path or URL instead.
* Redact any sensitive information, such as API keys, tokens, passwords, or personally identifiable information.
* If the user passed arguments, treat them as a description of what the next session will focus on and tailor the document accordingly.