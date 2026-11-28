---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview the user relentlessly about every aspect of the plan until reaching shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one by one.

- Ask **one question at a time**, always providing your recommended answer.
- For discrete design choices, use Antigravity's `ask_question` tool (listing your recommended choice first with `(Recommended)`). For open-ended questions, ask directly in concise prose.
- If a question can be answered by inspecting the codebase, explore the codebase directly (or delegate broad lookups to a `research` subagent via `invoke_subagent`) instead of asking the user.
