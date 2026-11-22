"""Tests for offline bilingual Typst CV and Cover Letter rendering."""

from __future__ import annotations

from pathlib import Path

import pypdf
import pytest
from pydantic import ValidationError

from job_agent.rendering import (
    CVBullet,
    CVEducation,
    CVExperience,
    CVProject,
    CVSkillCategory,
    CompileResult,
    DocumentCompiler,
    TailoredCoverLetter,
    TailoredCV,
    compile_application_pdfs,
)
from job_agent.schemas.preferences import LayoutGuardrails


def _extract_all_text(pdf_path: Path | str) -> str:
    reader = pypdf.PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _sample_en_cv(**overrides: object) -> TailoredCV:
    payload: dict[str, object] = {
        "language": "en",
        "full_name": "Sebastian McConnell",
        "email": "sebastian@example.com",
        "phone": "+45 12 34 56 78",
        "location": "Copenhagen, Denmark",
        "linkedin_url": "https://linkedin.com/in/sebastian",
        "github_url": "https://github.com/sebastian",
        "website_url": "https://sebastian.dev",
        "profile_summary": (
            "Junior backend and AI systems engineer building deterministic Python "
            "pipelines, APIs, and production LLM workflows."
        ),
        "experiences": [
            CVExperience(
                company="Nordic Data ApS",
                title="Junior Software Engineer",
                start_date="Jan 2024",
                end_date=None,
                location="Copenhagen",
                bullets=[
                    CVBullet(
                        lead="Workflow automation",
                        text="Built Python ingestion services processing 50k daily records.",
                    ),
                    CVBullet(
                        lead="API reliability",
                        text="Added Pydantic v2 validation and deterministic test suites.",
                    ),
                ],
            )
        ],
        "projects": [
            CVProject(
                name="Job Agent",
                url="https://github.com/sebastian/job-agent",
                bullets=[
                    CVBullet(
                        lead="Architecture",
                        text="Designed LangGraph tailoring workflow with Typst PDF output.",
                    )
                ],
            )
        ],
        "education": [
            CVEducation(
                institution="Technical University of Denmark",
                degree="BSc in Software Technology",
                start_date="2020",
                end_date="2023",
                location="Kongens Lyngby",
                highlights=["Thesis on deterministic evaluation harnesses for LLM agents."],
            )
        ],
        "skills": [
            CVSkillCategory(category="Languages", items=["Python", "SQL", "TypeScript"]),
            CVSkillCategory(category="Tools", items=["FastAPI", "Pydantic", "Typst", "Git"]),
        ],
        "certifications": ["AWS Cloud Practitioner"],
        "languages_spoken": ["English (Native)", "Danish (Conversational)"],
    }
    payload.update(overrides)
    return TailoredCV(**payload)  # type: ignore[arg-type]


def _sample_en_cover_letter(**overrides: object) -> TailoredCoverLetter:
    payload: dict[str, object] = {
        "language": "en",
        "full_name": "Sebastian McConnell",
        "email": "sebastian@example.com",
        "phone": "+45 12 34 56 78",
        "location": "Copenhagen, Denmark",
        "linkedin_url": "https://linkedin.com/in/sebastian",
        "recipient_company": "Acme Robotics ApS",
        "role_title": "Junior Backend Engineer",
        "date_str": "November 22, 2026",
        "greeting": "Dear Hiring Team,",
        "paragraphs": [
            "I am applying for the Junior Backend Engineer role at Acme Robotics ApS, where deterministic data pipelines and reliable Python services sit at the core of your platform.",
            "In my recent work at Nordic Data ApS, I built and tested ingestion services using Python, FastAPI, and Pydantic v2 while keeping latency predictable and schemas strictly validated.",
            "I would welcome the opportunity to bring this engineering discipline to your Copenhagen team and discuss how I can contribute from day one.",
        ],
        "sign_off": "Best regards,",
    }
    payload.update(overrides)
    return TailoredCoverLetter(**payload)  # type: ignore[arg-type]


def _sample_da_cv(**overrides: object) -> TailoredCV:
    payload: dict[str, object] = {
        "language": "da",
        "full_name": "Søren Østergaard Åkesson",
        "email": "soren@eksempel.dk",
        "phone": "+45 20 30 40 50",
        "location": "København Ø, Danmark",
        "linkedin_url": "https://linkedin.com/in/soren-aakesson",
        "profile_summary": (
            "Nyuddannet softwareudvikler med fokus på pålidelige dataplatforme, "
            "automatiserede arbejdsgange og skalerbare løsninger på tværs af backend-systemer."
        ),
        "experiences": [
            CVExperience(
                company="Grøn Energi A/S",
                title="Junior Udvikler",
                start_date="Jan 2024",
                end_date=None,
                location="Århus",
                bullets=[
                    CVBullet(
                        lead="Databehandling",
                        text="Udviklede løsninger til måling af strømforbrug og miljøpåvirkning.",
                    )
                ],
            )
        ],
        "projects": [
            CVProject(
                name="Søge- og Analyseplatform",
                url="https://github.com/soren/analyse",
                bullets=[
                    CVBullet(
                        lead="Fuldttekst-søgning",
                        text="Byggede hurtig indeksering af danske dokumenter med æ, ø og å.",
                    )
                ],
            )
        ],
        "education": [
            CVEducation(
                institution="Københavns Universitet",
                degree="Bachelor i Datalogi",
                start_date="2020",
                end_date="2023",
                location="København",
                highlights=["Speciale om pålidelige sprogmodeller på dansk."],
            )
        ],
        "skills": [
            CVSkillCategory(category="Programmering", items=["Python", "SQL", "Typst"]),
        ],
        "certifications": ["Sikkerhed i Cloud-miljøer"],
        "languages_spoken": ["Dansk (Modersmål)", "Engelsk (Flydende)"],
    }
    payload.update(overrides)
    return TailoredCV(**payload)  # type: ignore[arg-type]


def _sample_da_cover_letter(**overrides: object) -> TailoredCoverLetter:
    payload: dict[str, object] = {
        "language": "da",
        "full_name": "Søren Østergaard Åkesson",
        "email": "soren@eksempel.dk",
        "location": "København Ø, Danmark",
        "recipient_company": "Mærsk Teknologi A/S",
        "role_title": "Backend Udvikler",
        "date_str": "22. november 2026",
        "greeting": "Kære rekrutteringsteam,",
        "paragraphs": [
            "Jeg søger stillingen som Backend Udvikler hos Mærsk Teknologi A/S, hvor robuste datapipelines og høj driftsikkerhed skaber værdi på tværs af organisationen.",
            "Hos Grøn Energi A/S har jeg arbejdet med Python-baserede løsninger til løbende måling af strømforbrug i Århus og København med fuld testdækning.",
            "Jeg ser frem til en uddybende samtale om, hvordan mine erfaringer kan styrke jeres udviklingsteam.",
        ],
        "sign_off": "Med venlig hilsen,",
    }
    payload.update(overrides)
    return TailoredCoverLetter(**payload)  # type: ignore[arg-type]


def test_compile_english_pdfs_single_page_pass(tmp_path: Path) -> None:
    cv = _sample_en_cv()
    cover_letter = _sample_en_cover_letter()

    result = compile_application_pdfs(cv, cover_letter, tmp_path)

    assert isinstance(result, CompileResult)
    assert result.passed is True
    assert result.cv_pages == 1
    assert result.cover_letter_pages == 1
    assert result.overflow_feedback == []

    cv_pdf = Path(result.cv_pdf_path)
    cl_pdf = Path(result.cover_letter_pdf_path)
    assert cv_pdf.is_file() and cv_pdf.stat().st_size > 0
    assert cl_pdf.is_file() and cl_pdf.stat().st_size > 0

    cv_text = _extract_all_text(cv_pdf)
    for heading in (
        "Profile",
        "Experience",
        "Projects",
        "Education",
        "Skills",
        "Certifications",
        "Languages",
    ):
        assert heading in cv_text
    assert "Sebastian McConnell" in cv_text
    assert "Workflow automation:" in cv_text

    cl_text = _extract_all_text(cl_pdf)
    assert "Acme Robotics ApS" in cl_text
    assert "Junior Backend Engineer" in cl_text
    assert "Dear Hiring Team," in cl_text
    assert "Best regards," in cl_text


def test_compile_danish_pdfs_preserves_utf8_and_localized_headings(tmp_path: Path) -> None:
    cv = _sample_da_cv()
    cover_letter = _sample_da_cover_letter()

    result = compile_application_pdfs(cv, cover_letter, tmp_path)

    assert result.passed is True
    assert result.cv_pages == 1
    assert result.cover_letter_pages == 1

    cv_text = _extract_all_text(result.cv_pdf_path)
    for heading in (
        "Profil",
        "Erfaring",
        "Projekter",
        "Uddannelse",
        "Kompetencer",
        "Certificeringer",
        "Sprog",
    ):
        assert heading in cv_text
    assert "Søren Østergaard Åkesson" in cv_text
    assert "København" in cv_text
    assert "Århus" in cv_text
    assert "æ, ø og å" in cv_text
    assert "Nu" in cv_text

    cl_text = _extract_all_text(result.cover_letter_pdf_path)
    assert "Mærsk Teknologi A/S" in cl_text
    assert "Kære rekrutteringsteam," in cl_text
    assert "Århus" in cl_text
    assert "København" in cl_text


def test_special_characters_render_without_typst_syntax_errors(tmp_path: Path) -> None:
    cv = _sample_en_cv(
        profile_summary="Worked on C# / F# migrations, $100k budgets, @scale & <xml> *bold* _raw_ \\ paths."
    )
    cl = _sample_en_cover_letter()

    result = compile_application_pdfs(cv, cl, tmp_path)
    assert result.passed is True
    text = _extract_all_text(result.cv_pdf_path)
    assert "C# / F#" in text
    assert "$100k" in text


@pytest.mark.parametrize("bad_size", [8.9, 8.99, 12.01, 12.5, float("nan"), True])
def test_body_font_size_outside_hard_bounds_raises_value_error(
    tmp_path: Path, bad_size: float
) -> None:
    compiler = DocumentCompiler()
    cv = _sample_en_cv()
    cl = _sample_en_cover_letter()
    guardrails = LayoutGuardrails(min_font_size_pt=9.0, max_body_font_size_pt=12.0)

    with pytest.raises(ValueError):
        compiler.compile_application(
            cv,
            cl,
            tmp_path,
            body_font_size_pt=bad_size,
            guardrails=guardrails,
        )


def test_body_font_size_violating_guardrails_raises_value_error(tmp_path: Path) -> None:
    compiler = DocumentCompiler()
    cv = _sample_en_cv()
    cl = _sample_en_cover_letter()
    guardrails = LayoutGuardrails(min_font_size_pt=10.5, max_body_font_size_pt=11.5)

    with pytest.raises(ValueError, match="LayoutGuardrails"):
        compiler.compile_application(
            cv, cl, tmp_path, body_font_size_pt=10.0, guardrails=guardrails
        )

    with pytest.raises(ValueError, match="LayoutGuardrails"):
        compiler.compile_application(
            cv, cl, tmp_path, body_font_size_pt=12.0, guardrails=guardrails
        )

    ok_result = compiler.compile_application(
        cv, cl, tmp_path, body_font_size_pt=11.0, guardrails=guardrails
    )
    assert ok_result.passed is True


def test_min_body_font_size_9pt_allowed_when_guardrails_permit(tmp_path: Path) -> None:
    guardrails = LayoutGuardrails(min_font_size_pt=9.0, max_body_font_size_pt=12.0)
    result = compile_application_pdfs(
        _sample_en_cv(),
        _sample_en_cover_letter(),
        tmp_path,
        body_font_size_pt=9.0,
        guardrails=guardrails,
    )
    assert result.passed is True
    assert result.cv_pages == 1


def test_two_page_cv_overflow_detected_with_feedback(tmp_path: Path) -> None:
    heavy_experiences = [
        CVExperience(
            company=f"Company {i} ApS",
            title=f"Software Engineer {i}",
            start_date="Jan 2022",
            end_date="Dec 2024",
            location="Copenhagen",
            bullets=[
                CVBullet(
                    lead=f"Initiative {j}",
                    text=(
                        "Designed and operated distributed Python microservices, schema validation "
                        "layers, and automated integration benchmarks across multiple environments."
                    ),
                )
                for j in range(5)
            ],
        )
        for i in range(6)
    ]
    heavy_cv = _sample_en_cv(experiences=heavy_experiences)
    cl = _sample_en_cover_letter()

    result = compile_application_pdfs(heavy_cv, cl, tmp_path)

    assert result.passed is False
    assert result.cv_pages >= 2
    assert result.cover_letter_pages == 1
    assert len(result.overflow_feedback) == 1
    assert "max_cv_pages=1" in result.overflow_feedback[0]

    # When max_cv_pages allows the actual page count, compilation passes.
    relaxed = compile_application_pdfs(
        heavy_cv,
        cl,
        tmp_path / "relaxed",
        guardrails=LayoutGuardrails(max_cv_pages=result.cv_pages),
    )
    assert relaxed.passed is True
    assert relaxed.overflow_feedback == []


def test_two_page_cover_letter_overflow_detected_with_feedback(tmp_path: Path) -> None:
    long_paragraph = " ".join(
        [
            "In my engineering work, I focus on deterministic validation, clear domain modeling, "
            "and verifiable integration pipelines that remain maintainable over time."
        ]
        * 14
    )
    heavy_cl = _sample_en_cover_letter(paragraphs=[long_paragraph] * 5)

    result = compile_application_pdfs(_sample_en_cv(), heavy_cl, tmp_path)

    assert result.passed is False
    assert result.cv_pages == 1
    assert result.cover_letter_pages >= 2
    assert len(result.overflow_feedback) == 1
    assert "max_cover_letter_pages=1" in result.overflow_feedback[0]


def test_section_order_reorders_rendered_cv_sections(tmp_path: Path) -> None:
    reordered_cv = _sample_en_cv(
        section_order=["skills", "education", "projects", "experience"]
    )
    result = compile_application_pdfs(reordered_cv, _sample_en_cover_letter(), tmp_path)

    assert result.passed is True
    text = _extract_all_text(result.cv_pdf_path)

    pos_profile = text.index("Profile")
    pos_skills = text.index("Skills")
    pos_education = text.index("Education")
    pos_projects = text.index("Projects")
    pos_experience = text.index("Experience")

    assert pos_profile < pos_skills < pos_education < pos_projects < pos_experience


def test_cover_letter_paragraph_count_validation() -> None:
    with pytest.raises(ValidationError):
        _sample_en_cover_letter(paragraphs=["Too short", "Only two"])

    with pytest.raises(ValidationError):
        _sample_en_cover_letter(paragraphs=["One", "Two", "Three", "Four", "Five", "Six"])
