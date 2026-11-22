## ADDED Requirements

### Requirement: Bilingual Typst PDF rendering via Python wheel with open-source CV and custom Cover Letter templates
The system SHALL compile tailored CVs and Cover Letters to single-column, ATS-friendly PDFs using the `typst` Python package (`typst-py`, declared explicitly in `pyproject.toml` and locked in `uv.lock`, requiring no external system binary). The Writer SHALL output validated Pydantic models (`TailoredCV`, `TailoredCoverLetter`) serialized to JSON and passed to `typst.compile(..., sys_inputs=...)` against two vendored offline-capable templates:
- **CV (`cv.typ`):** Based on the open-source MIT-licensed `basic-resume` Typst template.
- **Cover Letter (`cover_letter.typ`):** A custom Typst template matching `basic-resume`'s header, typography, accent, and margins.
Both templates MUST render native UTF-8 Danish characters (`æ`, `ø`, `å`) cleanly and localize section headings automatically for `"da"` and `"en"`.

#### Scenario: Compile English CV and Cover Letter to PDF offline
- **WHEN** valid English `TailoredCV` and `TailoredCoverLetter` models are passed to the Typst compiler
- **THEN** the compiler SHALL produce readable single-column PDF files on disk without requiring network access or external CLI installations

#### Scenario: Compile Danish CV and Cover Letter preserving æ, ø, å and Danish headings
- **WHEN** valid Danish (`language="da"`) `TailoredCV` and `TailoredCoverLetter` models containing `æ`, `ø`, and `å` are compiled
- **THEN** the resulting PDFs SHALL contain localized Danish headings (e.g., `Profil`, `Erfaring`, `Projekter`, `Uddannelse`, `Kompetencer`) and intact UTF-8 Danish characters

### Requirement: Structural body typography bounds and deterministic page-budget overflow loop
The Typst templates SHALL lock body text font size strictly within `LayoutGuardrails.min_font_size_pt` (`>= 9.0pt`) and `LayoutGuardrails.max_body_font_size_pt` (`<= 12.0pt`, default `10.0pt`) — scoped strictly to body text (excluding headers, sub-headers, and footers) — and preserve whitespace and margins. After compiling each PDF, Python SHALL deterministically count pages using `pypdf`. If `page_count > max_cv_pages` or `page_count > max_cover_letter_pages` and `internal_retry_count < 2`, the graph MUST route exact overflow feedback back to the Writer to trim content rather than shrinking fonts or margins.

#### Scenario: Single-page PDF passes compiler gate
- **WHEN** compiled CV and Cover Letter PDFs each have `page_count == 1` and `max_cv_pages == 1`, `max_cover_letter_pages == 1`
- **THEN** the Compiler node SHALL mark compilation as passed and proceed to the Human Review interrupt

#### Scenario: Multi-page overflow triggers content-trimming retry without shrinking font
- **WHEN** a compiled CV exceeds `max_cv_pages` (`page_count == 2`) and `internal_retry_count < 2`
- **THEN** the Compiler node SHALL keep the body font size and margins unchanged and route overflow feedback back to the Writer to shorten prose or prune lower-relevance bullets
