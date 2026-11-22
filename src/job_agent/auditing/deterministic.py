"""Pass 1 deterministic Python gate (0 tokens) for tailored CVs and Cover Letters."""

from __future__ import annotations

import re
from typing import Iterable, Literal

from job_agent.auditing.models import AuditResult, AuditViolation
from job_agent.rendering.models import TailoredCoverLetter, TailoredCV
from job_agent.schemas.profile import ExperienceEntry, MasterProfile

_EM_DASH_PATTERN = re.compile(r"—|--")

_ENGLISH_CONTRACTION_PATTERN = re.compile(
    r"\b(?:"
    r"i['’](?:m|ve|ll|d)|"
    r"(?:we|you|they)['’](?:re|ve|ll|d)|"
    r"(?:it|that|there|here|who|what|where|he|she)['’]s|"
    r"let['’]s|"
    r"(?:do|does|did|could|would|should|is|are|was|were|have|has|had|must|need|ai)n['’]t|"
    r"can['’]t|won['’]t"
    r")\b",
    re.IGNORECASE,
)

_BANNED_CLICHE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (phrase, re.compile(rf"\b{pattern}\b", re.IGNORECASE))
    for phrase, pattern in (
        ("i am writing to apply for", r"i am writing to apply for"),
        ("i am writing to express", r"i am writing to express"),
        ("please accept this letter as", r"please accept this letter as"),
        ("jeg skriver hermed for at søge", r"jeg skriver hermed for at søge"),
        ("delve into", r"delve(?:\s+into)?"),
        ("navigate the complexities", r"navigate the complexities"),
        ("stands as a testament", r"stands as a testament"),
        ("plays a pivotal role", r"plays a pivotal role"),
        ("plays a vital role", r"plays a vital role"),
        ("plays a crucial role", r"plays a crucial role"),
        ("underscores", r"underscores"),
        ("tapestry", r"tapestry"),
        ("cutting-edge", r"cutting-edge"),
        ("world-class", r"world-class"),
        ("results-driven", r"results-driven"),
        ("passionate self-starter", r"passionate self-starter"),
        ("hit the ground running", r"hit the ground running"),
        ("synergy", r"synergy"),
        ("synergized", r"synergized"),
        ("spearheaded", r"spearheaded"),
        ("orchestrated", r"orchestrated"),
        ("pioneered", r"pioneered"),
        ("navigere i kompleksiteten", r"navigere i kompleksiteten"),
        ("spiller en afgørende rolle", r"spiller en afgørende rolle"),
        ("står som et vidnesbyrd", r"står som et vidnesbyrd"),
        ("banebrydende", r"banebrydende"),
        ("dynamisk miljø", r"dynamisk miljø"),
        ("proaktiv holdspiller", r"proaktiv holdspiller"),
    )
)

_PLACEHOLDER_PATTERN = re.compile(
    r"\{\{[^}]*\}\}"
    r"|\[\[[^\]]*\]\]"
    r"|\[(?:Company|Role|Virksomhed)\]"
    r"|<(?:company|role)>"
    r"|\b(?:TBD|TODO)\b",
    re.IGNORECASE,
)

_PARENTHESES_PATTERN = re.compile(r"\([^)]*\)|[()]")

_EXPECTED_SIGN_OFF: dict[Literal["en", "da"], str] = {
    "en": "Kind Regards,",
    "da": "Med venlig hilsen,",
}


def _normalize_text(value: str | None) -> str:
    """Normalize whitespace and case for anchor comparison."""
    if not value:
        return ""
    return " ".join(value.split()).casefold()


def _extract_snippet(text: str, match: re.Match[str], radius: int = 24) -> str:
    """Extract a readable snippet centered around a regex match."""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end].strip()


def _iter_cv_prose_fields(cv: TailoredCV) -> Iterable[tuple[str, str]]:
    """Yield (location, text) pairs for prose fields in TailoredCV."""
    yield "cv.profile_summary", cv.profile_summary
    for e_idx, exp in enumerate(cv.experiences):
        for b_idx, bullet in enumerate(exp.bullets):
            combined = f"{bullet.lead}: {bullet.text}" if bullet.lead else bullet.text
            yield f"cv.experiences[{e_idx}].bullets[{b_idx}]", combined
    for p_idx, proj in enumerate(cv.projects):
        for b_idx, bullet in enumerate(proj.bullets):
            combined = f"{bullet.lead}: {bullet.text}" if bullet.lead else bullet.text
            yield f"cv.projects[{p_idx}].bullets[{b_idx}]", combined
    for ed_idx, edu in enumerate(cv.education):
        for h_idx, highlight in enumerate(edu.highlights):
            yield f"cv.education[{ed_idx}].highlights[{h_idx}]", highlight


def _iter_cv_all_text_fields(cv: TailoredCV) -> Iterable[tuple[str, str]]:
    """Yield (location, text) pairs for all text fields in TailoredCV."""
    yield "cv.full_name", cv.full_name
    yield "cv.email", cv.email
    if cv.phone:
        yield "cv.phone", cv.phone
    if cv.location:
        yield "cv.location", cv.location
    yield "cv.profile_summary", cv.profile_summary

    for e_idx, exp in enumerate(cv.experiences):
        yield f"cv.experiences[{e_idx}].company", exp.company
        yield f"cv.experiences[{e_idx}].title", exp.title
        yield f"cv.experiences[{e_idx}].start_date", exp.start_date
        if exp.end_date:
            yield f"cv.experiences[{e_idx}].end_date", exp.end_date
        if exp.location:
            yield f"cv.experiences[{e_idx}].location", exp.location
        for b_idx, bullet in enumerate(exp.bullets):
            combined = f"{bullet.lead}: {bullet.text}" if bullet.lead else bullet.text
            yield f"cv.experiences[{e_idx}].bullets[{b_idx}]", combined

    for p_idx, proj in enumerate(cv.projects):
        yield f"cv.projects[{p_idx}].name", proj.name
        if proj.url:
            yield f"cv.projects[{p_idx}].url", proj.url
        for b_idx, bullet in enumerate(proj.bullets):
            combined = f"{bullet.lead}: {bullet.text}" if bullet.lead else bullet.text
            yield f"cv.projects[{p_idx}].bullets[{b_idx}]", combined

    for ed_idx, edu in enumerate(cv.education):
        yield f"cv.education[{ed_idx}].institution", edu.institution
        yield f"cv.education[{ed_idx}].degree", edu.degree
        if edu.start_date:
            yield f"cv.education[{ed_idx}].start_date", edu.start_date
        if edu.end_date:
            yield f"cv.education[{ed_idx}].end_date", edu.end_date
        if edu.location:
            yield f"cv.education[{ed_idx}].location", edu.location
        for h_idx, highlight in enumerate(edu.highlights):
            yield f"cv.education[{ed_idx}].highlights[{h_idx}]", highlight

    for s_idx, skill_cat in enumerate(cv.skills):
        yield f"cv.skills[{s_idx}].category", skill_cat.category
        for i_idx, item in enumerate(skill_cat.items):
            yield f"cv.skills[{s_idx}].items[{i_idx}]", item

    for c_idx, cert in enumerate(cv.certifications):
        yield f"cv.certifications[{c_idx}]", cert

    for l_idx, lang in enumerate(cv.languages_spoken):
        yield f"cv.languages_spoken[{l_idx}]", lang


def _iter_cover_letter_prose_fields(cover_letter: TailoredCoverLetter) -> Iterable[tuple[str, str]]:
    """Yield (location, text) pairs for cover letter greeting, paragraphs, and sign-off."""
    yield "cover_letter.greeting", cover_letter.greeting
    for p_idx, paragraph in enumerate(cover_letter.paragraphs):
        yield f"cover_letter.paragraph_{p_idx + 1}", paragraph
    yield "cover_letter.sign_off", cover_letter.sign_off


def _iter_cover_letter_all_text_fields(cover_letter: TailoredCoverLetter) -> Iterable[tuple[str, str]]:
    """Yield (location, text) pairs for all text fields in TailoredCoverLetter."""
    yield "cover_letter.recipient_company", cover_letter.recipient_company
    yield "cover_letter.role_title", cover_letter.role_title
    yield "cover_letter.date_str", cover_letter.date_str
    yield from _iter_cover_letter_prose_fields(cover_letter)


def _check_em_dashes(
    document: Literal["cv", "cover_letter"],
    fields: Iterable[tuple[str, str]],
    violations: list[AuditViolation],
) -> None:
    for location, text in fields:
        match = _EM_DASH_PATTERN.search(text)
        if match:
            violations.append(
                AuditViolation(
                    document=document,
                    location=location,
                    rule="em_dash",
                    offending_snippet=_extract_snippet(text, match),
                    fix_instruction=(
                        "Replace em-dashes ('—') and double hyphens ('--') with a comma, "
                        "period, or semicolon."
                    ),
                )
            )


def _check_english_contractions(
    cover_letter: TailoredCoverLetter,
    violations: list[AuditViolation],
) -> None:
    if cover_letter.language != "en":
        return
    for location, text in _iter_cover_letter_prose_fields(cover_letter):
        for match in _ENGLISH_CONTRACTION_PATTERN.finditer(text):
            violations.append(
                AuditViolation(
                    document="cover_letter",
                    location=location,
                    rule="english_contraction",
                    offending_snippet=match.group(0),
                    fix_instruction=(
                        f"Expand the contraction '{match.group(0)}' to its full uncontracted "
                        "English form."
                    ),
                )
            )


def _check_banned_cliches(
    document: Literal["cv", "cover_letter"],
    fields: Iterable[tuple[str, str]],
    violations: list[AuditViolation],
) -> None:
    for location, text in fields:
        for phrase, pattern in _BANNED_CLICHE_PATTERNS:
            match = pattern.search(text)
            if match:
                violations.append(
                    AuditViolation(
                        document=document,
                        location=location,
                        rule="banned_ai_cliche",
                        offending_snippet=match.group(0),
                        fix_instruction=(
                            f"Remove the banned cliché '{phrase}' and rewrite with plain, "
                            "concrete language grounded in verified experience."
                        ),
                    )
                )


def _check_placeholders(
    document: Literal["cv", "cover_letter"],
    fields: Iterable[tuple[str, str]],
    violations: list[AuditViolation],
) -> None:
    for location, text in fields:
        for match in _PLACEHOLDER_PATTERN.finditer(text):
            violations.append(
                AuditViolation(
                    document=document,
                    location=location,
                    rule="placeholder_token",
                    offending_snippet=match.group(0),
                    fix_instruction=(
                        f"Replace leftover placeholder token '{match.group(0)}' with concrete, "
                        "verified text."
                    ),
                )
            )


def _check_cover_letter_word_count(
    cover_letter: TailoredCoverLetter,
    min_words: int,
    max_words: int,
    violations: list[AuditViolation],
) -> None:
    word_count = sum(len(paragraph.split()) for paragraph in cover_letter.paragraphs)
    if word_count < min_words:
        violations.append(
            AuditViolation(
                document="cover_letter",
                location="cover_letter.paragraphs",
                rule="cover_letter_word_count",
                offending_snippet=f"{word_count} words",
                fix_instruction=(
                    f"Expand cover letter body paragraphs from {word_count} words to within "
                    f"{min_words}-{max_words} words using concrete verified details."
                ),
            )
        )
    elif word_count > max_words:
        violations.append(
            AuditViolation(
                document="cover_letter",
                location="cover_letter.paragraphs",
                rule="cover_letter_word_count",
                offending_snippet=f"{word_count} words",
                fix_instruction=(
                    f"Tighten cover letter body paragraphs from {word_count} words to within "
                    f"{min_words}-{max_words} words without dropping core technical proof."
                ),
            )
        )


def _check_cover_letter_sign_off(
    cover_letter: TailoredCoverLetter,
    violations: list[AuditViolation],
) -> None:
    expected = _EXPECTED_SIGN_OFF[cover_letter.language]
    if cover_letter.sign_off.strip() != expected:
        violations.append(
            AuditViolation(
                document="cover_letter",
                location="cover_letter.sign_off",
                rule="invalid_sign_off",
                offending_snippet=cover_letter.sign_off,
                fix_instruction=f"Replace sign-off with the exact string '{expected}'.",
            )
        )


def _check_exclamation_marks(
    cv: TailoredCV,
    cover_letter: TailoredCoverLetter,
    violations: list[AuditViolation],
) -> None:
    for location, text in _iter_cv_all_text_fields(cv):
        if "!" in text:
            violations.append(
                AuditViolation(
                    document="cv",
                    location=location,
                    rule="exclamation_mark",
                    offending_snippet=text,
                    fix_instruction="Remove all exclamation marks ('!') from the CV.",
                )
            )

    if "!" in cover_letter.greeting:
        violations.append(
            AuditViolation(
                document="cover_letter",
                location="cover_letter.greeting",
                rule="exclamation_mark",
                offending_snippet=cover_letter.greeting,
                fix_instruction="Remove '!' from the cover letter greeting.",
            )
        )

    for idx, paragraph in enumerate(cover_letter.paragraphs[:-1]):
        if "!" in paragraph:
            violations.append(
                AuditViolation(
                    document="cover_letter",
                    location=f"cover_letter.paragraph_{idx + 1}",
                    rule="exclamation_mark",
                    offending_snippet=paragraph,
                    fix_instruction=(
                        "Remove '!' from this paragraph; exclamation marks are only allowed "
                        "once on the final closing paragraph."
                    ),
                )
            )

    if "!" in cover_letter.sign_off:
        violations.append(
            AuditViolation(
                document="cover_letter",
                location="cover_letter.sign_off",
                rule="exclamation_mark",
                offending_snippet=cover_letter.sign_off,
                fix_instruction="Remove '!' from the cover letter sign-off.",
            )
        )

    last_paragraph = cover_letter.paragraphs[-1]
    if last_paragraph.count("!") > 1:
        violations.append(
            AuditViolation(
                document="cover_letter",
                location=f"cover_letter.paragraph_{len(cover_letter.paragraphs)}",
                rule="exclamation_mark",
                offending_snippet=last_paragraph,
                fix_instruction=(
                    "Keep at most one '!' across the entire cover letter, placed on the "
                    "final closing sentence."
                ),
            )
        )


def _check_cover_letter_parentheses(
    cover_letter: TailoredCoverLetter,
    violations: list[AuditViolation],
) -> None:
    for idx, paragraph in enumerate(cover_letter.paragraphs):
        match = _PARENTHESES_PATTERN.search(paragraph)
        if match:
            violations.append(
                AuditViolation(
                    document="cover_letter",
                    location=f"cover_letter.paragraph_{idx + 1}",
                    rule="parentheses_in_cover_letter",
                    offending_snippet=_extract_snippet(paragraph, match),
                    fix_instruction=(
                        "Remove parentheses from cover letter prose and integrate the aside "
                        "into clean sentence phrasing or drop it."
                    ),
                )
            )


def _fact_contains(facts_folded: str, value: str | None) -> bool:
    """Return True if a non-empty anchor string appears verbatim (case-insensitive) in facts."""
    if not value or not value.strip():
        return False
    return _normalize_text(value) in facts_folded


def _experience_matches_entry(
    company: str,
    title: str,
    start_date: str,
    end_date: str | None,
    entry: ExperienceEntry,
) -> bool:
    """Return True if all four CVExperience anchor fields match a MasterProfile entry."""
    return (
        _normalize_text(company) == _normalize_text(entry.company)
        and _normalize_text(title) == _normalize_text(entry.title)
        and _normalize_text(start_date) == _normalize_text(entry.start_date)
        and _normalize_text(end_date) == _normalize_text(entry.end_date)
    )


def _experience_verified_by_facts(
    company: str,
    title: str,
    start_date: str,
    end_date: str | None,
    profile: MasterProfile,
    facts_folded: str,
) -> bool:
    """Return True if an experience is fully stated or corrected in session_verified_facts."""
    if not facts_folded:
        return False

    if (
        _fact_contains(facts_folded, company)
        and _fact_contains(facts_folded, title)
        and _fact_contains(facts_folded, start_date)
        and (not _normalize_text(end_date) or _fact_contains(facts_folded, end_date))
    ):
        return True

    # Support targeted user corrections to an existing MasterProfile company anchor.
    for entry in profile.experiences:
        if _normalize_text(company) != _normalize_text(entry.company):
            continue
        title_ok = (
            _normalize_text(title) == _normalize_text(entry.title)
            or _fact_contains(facts_folded, title)
        )
        start_ok = (
            _normalize_text(start_date) == _normalize_text(entry.start_date)
            or _fact_contains(facts_folded, start_date)
        )
        end_ok = (
            _normalize_text(end_date) == _normalize_text(entry.end_date)
            or (bool(_normalize_text(end_date)) and _fact_contains(facts_folded, end_date))
        )
        if title_ok and start_ok and end_ok:
            return True

    return False


def _check_anchor_grounding(
    cv: TailoredCV,
    profile: MasterProfile,
    session_verified_facts: list[str] | None,
    violations: list[AuditViolation],
) -> None:
    facts_folded = _normalize_text(" ".join(session_verified_facts or []))

    for idx, exp in enumerate(cv.experiences):
        matched_profile = any(
            _experience_matches_entry(
                exp.company, exp.title, exp.start_date, exp.end_date, entry
            )
            for entry in profile.experiences
        )
        if matched_profile:
            continue
        if _experience_verified_by_facts(
            exp.company, exp.title, exp.start_date, exp.end_date, profile, facts_folded
        ):
            continue

        date_range = f"{exp.start_date} - {exp.end_date or 'Present'}"
        violations.append(
            AuditViolation(
                document="cv",
                location=f"cv.experiences[{idx}]",
                rule="unverified_experience_anchor",
                offending_snippet=f"{exp.title} at {exp.company} ({date_range})",
                fix_instruction=(
                    "Use exact company, title, start_date, and end_date from MasterProfile "
                    "or session_verified_facts; remove or correct any unverified anchor."
                ),
            )
        )

    profile_institutions = {_normalize_text(edu.institution) for edu in profile.education}
    for idx, edu in enumerate(cv.education):
        inst_norm = _normalize_text(edu.institution)
        if inst_norm in profile_institutions or _fact_contains(facts_folded, edu.institution):
            continue
        violations.append(
            AuditViolation(
                document="cv",
                location=f"cv.education[{idx}]",
                rule="unverified_education_anchor",
                offending_snippet=edu.institution,
                fix_instruction=(
                    "Use an exact education institution from MasterProfile or "
                    "session_verified_facts."
                ),
            )
        )


def run_deterministic_audit(
    cv: TailoredCV,
    cover_letter: TailoredCoverLetter,
    profile: MasterProfile,
    session_verified_facts: list[str] | None = None,
    *,
    min_words: int = 250,
    max_words: int = 380,
) -> AuditResult:
    """Run Pass 1 deterministic checks (0 tokens) on a tailored CV and Cover Letter."""
    violations: list[AuditViolation] = []

    cv_prose = list(_iter_cv_prose_fields(cv))
    cl_prose = list(_iter_cover_letter_prose_fields(cover_letter))

    _check_em_dashes("cv", cv_prose, violations)
    _check_em_dashes("cover_letter", cl_prose, violations)

    _check_english_contractions(cover_letter, violations)

    _check_banned_cliches("cv", cv_prose, violations)
    _check_banned_cliches("cover_letter", cl_prose, violations)

    _check_cover_letter_word_count(cover_letter, min_words, max_words, violations)
    _check_cover_letter_sign_off(cover_letter, violations)
    _check_exclamation_marks(cv, cover_letter, violations)

    _check_placeholders("cv", _iter_cv_all_text_fields(cv), violations)
    _check_placeholders("cover_letter", _iter_cover_letter_all_text_fields(cover_letter), violations)

    _check_cover_letter_parentheses(cover_letter, violations)
    _check_anchor_grounding(cv, profile, session_verified_facts, violations)

    return AuditResult(passed=not violations, violations=violations)
