---
name: implement
description: "Explicitly-invoked workflow to implement a piece of work based on a spec, OpenSpec change, or set of tickets."
---

Implement the work described by the user in the spec, active OpenSpec change (`openspec/changes/`), or tickets. Only run this workflow when explicitly asked to implement.

- Follow the `tdd` skill where possible, testing at pre-agreed seams.
- Run typechecking regularly, single test files regularly, and the full test suite once at the end.
- Invoke the `code-review` skill when implementation is finished.
- Commit your work to the current non-`main` branch.
