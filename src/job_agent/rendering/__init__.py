"""Typst document rendering models and offline PDF compiler."""

from job_agent.rendering.compiler import (
    DEFAULT_BODY_FONT_SIZE_PT,
    DocumentCompiler,
    MAX_BODY_FONT_SIZE_PT,
    MIN_BODY_FONT_SIZE_PT,
    compile_application_pdfs,
    count_pdf_pages,
)
from job_agent.rendering.models import (
    CVBullet,
    CVEducation,
    CVExperience,
    CVProject,
    CVSectionKey,
    CVSkillCategory,
    CompileResult,
    TailoredCV,
    TailoredCoverLetter,
)

__all__ = [
    "CVBullet",
    "CVEducation",
    "CVExperience",
    "CVProject",
    "CVSectionKey",
    "CVSkillCategory",
    "CompileResult",
    "DEFAULT_BODY_FONT_SIZE_PT",
    "DocumentCompiler",
    "MAX_BODY_FONT_SIZE_PT",
    "MIN_BODY_FONT_SIZE_PT",
    "TailoredCV",
    "TailoredCoverLetter",
    "compile_application_pdfs",
    "count_pdf_pages",
]
