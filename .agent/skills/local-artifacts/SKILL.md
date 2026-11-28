---
name: local-artifacts
description: "Create and manage project-scoped, diagram-heavy local HTML artifacts in .artifacts/ to visually explain system architecture, logic, tools, or concepts."
---

Launch a lightweight Gemini 4 **Hydrogen** sub-agent with relevant context to complete the following task:

## Scope & Storage

* Check for an `.artifacts/` directory at the root of the current project workspace. If it does not exist, create it.
  * If needed, create a topic- or session-specific sub-directory inside `.artifacts/` related to the current session context.
* Place the generated HTML files in `.artifacts/` (or the appropriate sub-directory) based on the current session context.
* Artifacts belonging to the same collection or sub-directory should include seamless navigation between them (e.g., a clean shared top bar or sidebar linking sibling pages).
* These artifacts are strictly project-local HTML files stored in `.artifacts/` inside the workspace, separate from Antigravity's conversation-level artifact store or other platform-hosted artifacts.

## Visual & Diagram Standards

* **Diagram-first, text-light:** Make visual diagrams the centerpiece of every page so the reader can understand a system's architecture, boundaries, and data flows at a glance. Replace walls of prose with layered architecture maps, flow diagrams, sequence/lifecycle views, and short, plain-English callouts with minimal technical jargon.
* **Clean, bespoke visuals:** Draw crisp, well-spaced inline SVG (or HTML/SVG hybrid) diagrams with clear visual hierarchy, generous whitespace, aligned grids, clean directional arrows, and zero overlapping labels or cramped boxes.
* **Colourful with purpose:** Use a vibrant, cohesive colour palette where colour encodes meaning (e.g., distinct hues for layers, actors, services, storage, or flow types), paired with a compact legend and strong text contrast so relationships jump out immediately.
* **Interactive exploration:** Add lightweight interactivity that deepens understanding without clutter—such as clicking or hovering nodes to highlight upstream/downstream connections, stepping through a request/data flow, toggling architectural layers, or expanding concise detail cards.
* **Self-contained files:** Keep each HTML artifact completely self-contained (inline CSS/JS/SVG, no build step or fragile runtime dependencies) so it opens cleanly straight from `.artifacts/`.
