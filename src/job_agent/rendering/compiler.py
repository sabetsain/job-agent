"""Offline Typst PDF compiler and deterministic page-budget validator."""

from __future__ import annotations

import math
from pathlib import Path

import pypdf
import typst
from pydantic import BaseModel

from job_agent.rendering.models import CompileResult, TailoredCoverLetter, TailoredCV
from job_agent.schemas.preferences import LayoutGuardrails

MIN_BODY_FONT_SIZE_PT: float = 9.0
MAX_BODY_FONT_SIZE_PT: float = 12.0
DEFAULT_BODY_FONT_SIZE_PT: float = 10.0

TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"
DEFAULT_CV_TEMPLATE: Path = TEMPLATES_DIR / "cv.typ"
DEFAULT_COVER_LETTER_TEMPLATE: Path = TEMPLATES_DIR / "cover_letter.typ"


def _validate_body_font_size(
    body_font_size_pt: float,
    guardrails: LayoutGuardrails,
) -> float:
    """Validate that body font size satisfies both hard bounds and layout guardrails."""
    if isinstance(body_font_size_pt, bool) or not math.isfinite(body_font_size_pt):
        raise ValueError(f"body_font_size_pt must be a finite number, got {body_font_size_pt!r}")

    size = float(body_font_size_pt)
    if size < MIN_BODY_FONT_SIZE_PT or size > MAX_BODY_FONT_SIZE_PT:
        raise ValueError(
            f"body_font_size_pt={size} is outside hard structural bounds "
            f"[{MIN_BODY_FONT_SIZE_PT}, {MAX_BODY_FONT_SIZE_PT}]"
        )
    if size < guardrails.min_font_size_pt or size > guardrails.max_body_font_size_pt:
        raise ValueError(
            f"body_font_size_pt={size} violates LayoutGuardrails bounds "
            f"[{guardrails.min_font_size_pt}, {guardrails.max_body_font_size_pt}]"
        )
    return size


def count_pdf_pages(pdf_path: Path | str) -> int:
    """Count pages in a compiled PDF deterministically using pypdf."""
    reader = pypdf.PdfReader(str(pdf_path))
    return len(reader.pages)


class DocumentCompiler:
    """Compiles TailoredCV and TailoredCoverLetter models to PDFs via typst-py."""

    def __init__(
        self,
        *,
        cv_template_path: Path | str | None = None,
        cover_letter_template_path: Path | str | None = None,
    ) -> None:
        self.cv_template_path = Path(cv_template_path or DEFAULT_CV_TEMPLATE)
        self.cover_letter_template_path = Path(
            cover_letter_template_path or DEFAULT_COVER_LETTER_TEMPLATE
        )
        for template_path in (self.cv_template_path, self.cover_letter_template_path):
            if not template_path.is_file():
                raise FileNotFoundError(f"Typst template not found: {template_path}")

    def _compile_document(
        self,
        model: BaseModel,
        template_path: Path,
        output_path: Path | str,
        *,
        body_font_size_pt: float,
        guardrails: LayoutGuardrails,
    ) -> tuple[Path, int]:
        """Compile a single Pydantic document model against a Typst template and count pages."""
        validated_size = _validate_body_font_size(body_font_size_pt, guardrails)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        typst.compile(
            str(template_path),
            output=str(out_path),
            sys_inputs={
                "data": model.model_dump_json(),
                "body_font_size_pt": str(validated_size),
            },
        )
        page_count = count_pdf_pages(out_path)
        return out_path, page_count

    def compile_cv(
        self,
        cv: TailoredCV,
        output_path: Path | str,
        *,
        body_font_size_pt: float = DEFAULT_BODY_FONT_SIZE_PT,
        guardrails: LayoutGuardrails | None = None,
    ) -> tuple[Path, int]:
        """Compile a TailoredCV to PDF and return (output_path, page_count)."""
        resolved_guardrails = guardrails or LayoutGuardrails()
        return self._compile_document(
            cv,
            self.cv_template_path,
            output_path,
            body_font_size_pt=body_font_size_pt,
            guardrails=resolved_guardrails,
        )

    def compile_cover_letter(
        self,
        cover_letter: TailoredCoverLetter,
        output_path: Path | str,
        *,
        body_font_size_pt: float = DEFAULT_BODY_FONT_SIZE_PT,
        guardrails: LayoutGuardrails | None = None,
    ) -> tuple[Path, int]:
        """Compile a TailoredCoverLetter to PDF and return (output_path, page_count)."""
        resolved_guardrails = guardrails or LayoutGuardrails()
        return self._compile_document(
            cover_letter,
            self.cover_letter_template_path,
            output_path,
            body_font_size_pt=body_font_size_pt,
            guardrails=resolved_guardrails,
        )

    def compile_application(
        self,
        cv: TailoredCV,
        cover_letter: TailoredCoverLetter,
        output_dir: Path | str,
        *,
        body_font_size_pt: float = DEFAULT_BODY_FONT_SIZE_PT,
        guardrails: LayoutGuardrails | None = None,
        cv_filename: str = "cv.pdf",
        cover_letter_filename: str = "cover_letter.pdf",
    ) -> CompileResult:
        """Compile both CV and Cover Letter PDFs and evaluate page-budget guardrails."""
        resolved_guardrails = guardrails or LayoutGuardrails()
        validated_size = _validate_body_font_size(body_font_size_pt, resolved_guardrails)

        target_dir = Path(output_dir)
        cv_path, cv_pages = self.compile_cv(
            cv,
            target_dir / cv_filename,
            body_font_size_pt=validated_size,
            guardrails=resolved_guardrails,
        )
        cover_letter_path, cover_letter_pages = self.compile_cover_letter(
            cover_letter,
            target_dir / cover_letter_filename,
            body_font_size_pt=validated_size,
            guardrails=resolved_guardrails,
        )

        overflow_feedback: list[str] = []
        if cv_pages > resolved_guardrails.max_cv_pages:
            overflow_feedback.append(
                f"CV rendered to {cv_pages} pages, exceeding max_cv_pages="
                f"{resolved_guardrails.max_cv_pages}. Shorten prose or prune lower-relevance "
                f"bullets while keeping body font size ({validated_size}pt) and margins unchanged."
            )
        if cover_letter_pages > resolved_guardrails.max_cover_letter_pages:
            overflow_feedback.append(
                f"Cover letter rendered to {cover_letter_pages} pages, exceeding "
                f"max_cover_letter_pages={resolved_guardrails.max_cover_letter_pages}. Tighten "
                f"paragraph prose while keeping body font size ({validated_size}pt) and margins "
                f"unchanged."
            )

        return CompileResult(
            passed=not overflow_feedback,
            cv_pdf_path=str(cv_path),
            cover_letter_pdf_path=str(cover_letter_path),
            cv_pages=cv_pages,
            cover_letter_pages=cover_letter_pages,
            overflow_feedback=overflow_feedback,
        )


def compile_application_pdfs(
    cv: TailoredCV,
    cover_letter: TailoredCoverLetter,
    output_dir: Path | str,
    *,
    body_font_size_pt: float = DEFAULT_BODY_FONT_SIZE_PT,
    guardrails: LayoutGuardrails | None = None,
    cv_filename: str = "cv.pdf",
    cover_letter_filename: str = "cover_letter.pdf",
) -> CompileResult:
    """Compile a TailoredCV and TailoredCoverLetter into PDFs using default templates."""
    compiler = DocumentCompiler()
    return compiler.compile_application(
        cv,
        cover_letter,
        output_dir,
        body_font_size_pt=body_font_size_pt,
        guardrails=guardrails,
        cv_filename=cv_filename,
        cover_letter_filename=cover_letter_filename,
    )
