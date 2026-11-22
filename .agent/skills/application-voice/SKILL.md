---
name: application-voice
description: >
  Rework, draft, or audit CVs and Cover Letters in Sebastian McConnell's authentic writing voice
  (English and Danish) using his embedded Voice DNA profile. Use when tailoring application
  materials, transforming generic or AI-drafted CVs/cover letters into Sebastian's voice,
  or auditing drafts for AI tells.
---

# Application Voice Writer

Rewrite, draft, and audit CVs and Cover Letters in Sebastian McConnell's authentic voice (English and Danish) at ~80%+ voice fidelity, while upholding the principles in `docs/INTENT.md`.

Adapted from `robertguss/claude-code-toolkit` (`ghost-writer` + `writing-dna-discovery`) into a single read-only project skill with Sebastian's Voice DNA embedded directly in `references/voice-dna.md`.

## Core Principles

1. **Authentic Voice Over Generic Polish** — The goal is not abstract "corporate perfection," but prose that unmistakably reads like Sebastian wrote it. Preserve his directness, concrete technical specificity, and natural rhythm.
2. **Strict Truthfulness (Zero Fabrication)** — Per `docs/INTENT.md`, never invent, inflate, or extrapolate skills, metrics, titles, dates, or experiences. Reword, reorder, tighten, and translate faithfully; if a source draft contains an unverified claim or a job posting has a major unaddressed gap, flag it in the notes rather than fabricating.
3. **Bilingual Fluency** — Match the language of the job posting or input document (English → English DNA; Danish → Danish DNA). Never output awkward anglicized Danish or stiff literal translations.
4. **Design Integrity** — Keep CVs and Cover Letters tight and scannable (target 1-page cover letters of ~280–360 words; crisp, scannable CV bullets). Fit length by tightening prose, never by padding or cramming.
5. **Collaborative Partner** — If a source document has structural issues, vague claims, or conflicts with Sebastian's voice or `docs/INTENT.md`, surface them briefly and honestly in the notes. Sebastian always makes the final call.

## Required References

Always load before reworking or drafting:
- `references/voice-dna.md` — Read the **full document** (not only the briefing), including exemplars, punctuation rules, anti-patterns, and the relevant language section (English or Danish).
- `references/anti-ai-patterns.md` — Baseline AI tells to strip out during rewrites and final self-audit.

---

## Modes of Operation

### Mode 1: Rework / Voice-Match (Default)
Use when Sebastian provides an existing CV, Cover Letter, or AI-generated draft to rewrite into his voice.

**Step 1 — Diagnose the Input**
- Identify document type (**Cover Letter** vs. **CV** vs. **CV Profile/Bullets**) and language (**English** vs. **Danish**).
- Scan the input for:
  - AI tells (em-dashes, "I am writing to apply for...", significance puffery, superficial `-ing` participles, corporate buzzwords, mechanical rule-of-three).
  - Structural mismatches (e.g., generic cover letter opening instead of Sebastian's direct hook + credentials; dense paragraphs instead of bold-lead CV bullets).
  - Factual content to preserve 100% faithfully (projects, tools, metrics, company names, outcomes).

**Step 2 — Rework in Sebastian's Voice**
- Apply every relevant rule from `references/voice-dna.md`:
  - **Cover Letters:** Follow Sebastian's 4-paragraph arc (Direct hook + credentials → Concrete engineering/community proof → Technical depth/academic or project proof → Mission bridge + warm sign-off). Match his sentence rhythm (~18–21 words avg, mix of crisp punchy lines and substantive concrete sentences), punctuation (zero em-dashes, no contractions in cover letters, occasional semicolon for elaboration, max one `!` on the closing line), and sign-off (`Kind Regards,` / `Med venlig hilsen,`).
  - **CVs:** Use his crisp 3–4 sentence factual Profile (no fluff) and **bold-lead bullets** (`Label: Action verb + concrete stack + outcome`). Keep metrics exact (`~300`, `~1200`, `12`, etc. — only when present in the source/profile).
- Run a **self-audit** against `references/anti-ai-patterns.md` before outputting. If an AI tell slipped in, rewrite that sentence.

**Step 3 — Deliver Clean Output + Brief Notes**
Structure the response in this exact order:

1. **Reworked Document** — Clean, ready-to-use prose with **no inline annotations or commentary**.
2. **Voice & Anti-AI Notes** (concise, scannable):
   - **Key Voice Moves Applied:** 3–5 bullet points citing specific changes made to match `references/voice-dna.md`.
   - **AI Tells & Fluff Removed:** Specific phrases/structures stripped out (if any).
   - **Truthfulness Check:** Confirm all facts/metrics came from the input, or flag any ambiguous/unverified claims.
   - **Optional Second Angle:** Offer a brief 1-line note on an alternative framing if Sebastian wants a second version (e.g., *"Want a second angle that leads with X instead of Y?"*).

---

### Mode 2: Draft From Brief
Use when drafting a tailored CV or Cover Letter from scratch using Sebastian's Master Profile / verified facts + a job posting.
- Follow the same rules as Mode 1.
- Surface transferable experience where relevant (per `docs/INTENT.md`) without fabricating missing skills.
- Call out only **major** unaddressed gaps in the notes alongside the draft.

---

## Handling Edge Cases

- **Danish Register Confidence:** The Danish section in `references/voice-dna.md` is currently calibrated from 1 sample (`Offtentlig`). When reworking or drafting in Danish, note this briefly in the notes.
- **Tone Modifiers:** If Sebastian asks for `"my voice, but slightly more formal"` or `"more concise"`, apply it as a layer on top of his DNA without re-introducing banned anti-patterns (like em-dashes or corporate puffery).
- **Humor:** Keep cover letters and CVs grounded and sincere; never force jokes or witty asides.
- **Length Constraints:** If an input cover letter is bloated (450+ words), tighten it toward Sebastian's natural ~280–360 word single-page footprint while keeping his concrete details intact.
