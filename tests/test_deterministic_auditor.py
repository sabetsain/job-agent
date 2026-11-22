"""Unit tests for Pass 1 deterministic auditor and Pass 2 reasoning LLM auditor."""

from __future__ import annotations

import json
from typing import Any

from job_agent.auditing import (
    AuditResult,
    AuditViolation,
    run_deterministic_audit,
    run_llm_audit,
)
from job_agent.prompts import get_prompt
from job_agent.rendering.models import (
    CVBullet,
    CVEducation,
    CVExperience,
    CVProject,
    CVSkillCategory,
    TailoredCoverLetter,
    TailoredCV,
)
from job_agent.schemas.profile import (
    EducationEntry,
    ExperienceBullet,
    ExperienceEntry,
    Identity,
    LanguageProficiency,
    MasterProfile,
    ProjectEntry,
    SkillsCatalog,
)


def _sample_master_profile() -> MasterProfile:
    return MasterProfile(
        identity=Identity(
            full_name="Sebastian McConnell",
            email="sebastian@example.com",
            phone="+45 12 34 56 78",
            location="Copenhagen, Denmark",
            linkedin_url="https://linkedin.com/in/sebastian",
            github_url="https://github.com/sebastian",
            website_url="https://sebastian.dev",
        ),
        summary_seed="BSc in Computer Science & Data Science at University of Copenhagen with engineering experience at LEGO Group.",
        experiences=[
            ExperienceEntry(
                company="LEGO Group",
                title="Student Developer",
                start_date="2024-06",
                end_date="2025-12",
                location="Copenhagen, Denmark",
                bullets=[
                    ExperienceBullet(
                        label="Developer Enablement",
                        text="Built internal Python CLI tooling and CI templates used by ~300 engineers.",
                        metrics=["~300 engineers"],
                        skills=["Python", "GitHub Actions", "Docker"],
                    ),
                    ExperienceBullet(
                        label="Observability",
                        text="Maintained OpenTelemetry ingestion pipelines handling ~1200 events per minute.",
                        metrics=["~1200 events/min"],
                        skills=["Python", "OpenTelemetry", "Pulumi"],
                    ),
                ],
            )
        ],
        projects=[
            ProjectEntry(
                name="Deterministic Graph Orchestrator",
                url="https://github.com/sebastian/graph-orch",
                bullets=[
                    "Implemented stateful Python workflow engine with SQLite checkpointing and strict Pydantic schemas."
                ],
                skills=["Python", "LangGraph", "SQLite", "Pydantic"],
            )
        ],
        education=[
            EducationEntry(
                institution="University of Copenhagen",
                degree="BSc in Computer Science & Data Science",
                start_date="2022-09",
                end_date="2025-06",
                location="Copenhagen, Denmark",
                highlights=["Bachelor thesis on deterministic evaluation harnesses for agentic pipelines."],
            )
        ],
        languages=[
            LanguageProficiency(language="en", proficiency="Native"),
            LanguageProficiency(language="da", proficiency="Fluent"),
        ],
        skills=SkillsCatalog(
            languages=["Python", "TypeScript", "SQL"],
            frameworks=["FastAPI", "Pydantic", "LangGraph"],
            infrastructure=["Docker", "Pulumi", "GitHub Actions"],
            databases=["PostgreSQL", "SQLite"],
        ),
    )


def _clean_en_cv() -> TailoredCV:
    return TailoredCV(
        language="en",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        phone="+45 12 34 56 78",
        location="Copenhagen, Denmark",
        linkedin_url="https://linkedin.com/in/sebastian",
        github_url="https://github.com/sebastian",
        website_url="https://sebastian.dev",
        profile_summary=(
            "Computer Science & Data Science graduate from the University of Copenhagen "
            "with backend and developer tooling experience at LEGO Group. I build reliable "
            "Python services, CI/CD automation, and deterministic data pipelines with strict schema checks."
        ),
        experiences=[
            CVExperience(
                company="LEGO Group",
                title="Student Developer",
                start_date="2024-06",
                end_date="2025-12",
                location="Copenhagen, Denmark",
                bullets=[
                    CVBullet(
                        lead="Developer Enablement",
                        text="Built internal Python CLI tooling and GitHub Actions workflows adopted by ~300 engineers.",
                    ),
                    CVBullet(
                        lead="Observability Pipeline",
                        text="Maintained OpenTelemetry ingestion pipelines and Pulumi infrastructure handling ~1200 events per minute.",
                    ),
                ],
            )
        ],
        projects=[
            CVProject(
                name="Deterministic Graph Orchestrator",
                url="https://github.com/sebastian/graph-orch",
                bullets=[
                    CVBullet(
                        lead="Workflow Engine",
                        text="Implemented stateful Python orchestration with SQLite checkpointing and Pydantic v2 validation.",
                    )
                ],
            )
        ],
        education=[
            CVEducation(
                institution="University of Copenhagen",
                degree="BSc in Computer Science & Data Science",
                start_date="2022-09",
                end_date="2025-06",
                location="Copenhagen, Denmark",
                highlights=["Bachelor thesis on deterministic evaluation harnesses for agentic pipelines."],
            )
        ],
        skills=[
            CVSkillCategory(category="Languages", items=["Python", "TypeScript", "SQL"]),
            CVSkillCategory(category="Backend & Infra", items=["FastAPI", "Pydantic", "Docker", "Pulumi"]),
        ],
        languages_spoken=["English (Native)", "Danish (Fluent)"],
    )


def _clean_en_cover_letter() -> TailoredCoverLetter:
    return TailoredCoverLetter(
        language="en",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        phone="+45 12 34 56 78",
        location="Copenhagen, Denmark",
        linkedin_url="https://linkedin.com/in/sebastian",
        recipient_company="Nordic Cloud Systems",
        role_title="Junior Backend Engineer",
        date_str="November 22, 2026",
        greeting="Dear Hiring Team at Nordic Cloud Systems,",
        paragraphs=[
            (
                "Building telemetry ingestion services that reject malformed payloads before they hit "
                "downstream storage matches the engineering problems I enjoy solving most. Your open "
                "Junior Backend Engineer role caught my attention because Nordic Cloud Systems runs "
                "strictly typed Python services at high throughput across European customer clusters. "
                "I recently completed my BSc in Computer Science and Data Science at the University "
                "of Copenhagen, following eighteen months of hands-on backend and developer tooling "
                "work inside LEGO Group."
            ),
            (
                "At LEGO Group, I worked as a Student Developer building internal Python CLI tools, "
                "reusable GitHub Actions workflows, and OpenTelemetry ingestion pipelines. Our tooling "
                "supported ~300 engineers across product squads, while the telemetry collectors "
                "processed ~1200 events per minute with strict schema validation. I also helped "
                "maintain cloud infrastructure defined in Pulumi and containerized local test setups "
                "with Docker so teams could reproduce production failures before merging pull requests. "
                "That daily feedback loop taught me to keep interfaces simple, write deterministic tests, "
                "and document failure modes clearly for other developers."
            ),
            (
                "During my bachelor thesis and personal engineering work, I deepened my focus on "
                "reliable Python orchestration and data modeling. For my thesis at the University of "
                "Copenhagen, I designed deterministic evaluation harnesses for stateful workflows, "
                "combining SQLite persistence with Pydantic v2 contracts to catch regressions early. "
                "When I do not know a specific hosted vendor tool yet, I learn its primitives quickly "
                "by mapping them to infrastructure and CI concepts I have already shipped in production."
            ),
            (
                "Nordic Cloud Systems stands out to me as a pragmatic engineering team that values "
                "clean architecture, fast feedback cycles, and measurable reliability over hype. I am "
                "confident that my foundation in Python backend services, schema validation, and "
                "developer enablement will let me contribute steadily from my first sprint. I am excited "
                "by the opportunity to further discuss how my background fits the role!"
            ),
        ],
        sign_off="Kind Regards,",
    )


def _clean_da_cv() -> TailoredCV:
    return TailoredCV(
        language="da",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        phone="+45 12 34 56 78",
        location="København, Danmark",
        linkedin_url="https://linkedin.com/in/sebastian",
        github_url="https://github.com/sebastian",
        website_url="https://sebastian.dev",
        profile_summary=(
            "Bachelor i Datalogi og Datavidenskab fra University of Copenhagen med praktisk "
            "erfaring i backend-udvikling og udviklerværktøjer hos LEGO Group. Jeg bygger "
            "pålidelige Python-tjenester, CI/CD-automatisering og deterministiske datapipelines."
        ),
        experiences=[
            CVExperience(
                company="LEGO Group",
                title="Student Developer",
                start_date="2024-06",
                end_date="2025-12",
                location="København, Danmark",
                bullets=[
                    CVBullet(
                        lead="Udviklerværktøjer",
                        text="Byggede interne Python CLI-værktøjer og GitHub Actions-skabeloner brugt af ~300 udviklere.",
                    ),
                    CVBullet(
                        lead="Observability-pipeline",
                        text="Vedligeholdt OpenTelemetry-pipelines og Pulumi-infrastruktur med ~1200 hændelser i minuttet.",
                    ),
                ],
            )
        ],
        projects=[
            CVProject(
                name="Deterministic Graph Orchestrator",
                url="https://github.com/sebastian/graph-orch",
                bullets=[
                    CVBullet(
                        lead="Workflow-motor",
                        text="Implementerede tilstandsbaseret Python-orkestrering med SQLite og Pydantic v2.",
                    )
                ],
            )
        ],
        education=[
            CVEducation(
                institution="University of Copenhagen",
                degree="BSc i Datalogi og Datavidenskab",
                start_date="2022-09",
                end_date="2025-06",
                location="København, Danmark",
                highlights=["Bachelorprojekt om deterministiske evalueringsrammer til agent-pipelines."],
            )
        ],
        skills=[
            CVSkillCategory(category="Sprog", items=["Python", "TypeScript", "SQL"]),
            CVSkillCategory(category="Backend og Infra", items=["FastAPI", "Pydantic", "Docker", "Pulumi"]),
        ],
        languages_spoken=["Engelsk (Modersmål)", "Dansk (Flydende)"],
    )


def _clean_da_cover_letter() -> TailoredCoverLetter:
    return TailoredCoverLetter(
        language="da",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        phone="+45 12 34 56 78",
        location="København, Danmark",
        linkedin_url="https://linkedin.com/in/sebastian",
        recipient_company="Nordic Cloud Systems",
        role_title="Junior Backend-udvikler",
        date_str="22. november 2026",
        greeting="Kære ansættelsesteam hos Nordic Cloud Systems,",
        paragraphs=[
            (
                "At bygge datatjenester, der afviser ugyldige payloads før de rammer lageret, "
                "rammer lige ind i de tekniske problemer jeg trives bedst med at løse. Jeres opslag "
                "som Junior Backend-udvikler fangede min opmærksomhed, fordi Nordic Cloud Systems "
                "driver strengt typede Python-tjenester på tværs af europæiske kundeklynger. Jeg "
                "har for nylig afsluttet min bachelor i Datalogi og Datavidenskab på Københavns "
                "Universitet efter halvandet års praktisk udviklingsarbejde hos LEGO Group."
            ),
            (
                "Hos LEGO Group arbejdede jeg som Student Developer med interne Python CLI-værktøjer, "
                "genbrugelige GitHub Actions-pipelines og OpenTelemetry-indsamling. Vores værktøjer "
                "understøttede ~300 udviklere på tværs af produktteams, mens vores observability-pipeline "
                "behandlede ~1200 hændelser i minuttet med fast skemavalidering. Jeg var også med "
                "til at vedligeholde infrastruktur i Pulumi og køre lokale testmiljøer i Docker, så "
                "teams kunne reproducere fejl før kode blev flettet ind i hovedgrenen. Det lærte mig "
                "at holde grænseflader enkle, skrive deterministiske tests og dokumentere fejltilstande."
            ),
            (
                "I mit bachelorprojekt og egne tekniske projekter har jeg fokuseret på robust "
                "Python-orkestrering og datamodellering. Til mit bachelorprojekt udviklede jeg "
                "deterministiske evalueringsrammer for tilstandsbaserede workflows med SQLite og "
                "Pydantic v2 for at fange regressioner tidligt i forløbet. Når jeg endnu ikke kender "
                "et bestemt eksternt værktøj, sætter jeg mig hurtigt ind i dets grundprincipper ved "
                "at koble dem til de CI/CD- og infrastrukturmønstre, jeg allerede har kørt i produktion."
            ),
            (
                "Nordic Cloud Systems fremstår som et pragmatisk udviklingsmiljø, der prioriterer "
                "ren arkitektur, hurtig feedback og målbar driftssikkerhed frem for tom snak. Jeg "
                "er sikker på, at min baggrund med Python-tjenester, automatiserede tests, skemavalidering "
                "og udviklerunderstøttelse gør mig i stand til at bidrage stabilt til jeres platform fra "
                "første sprint i København. Jeg ser meget frem til muligheden for at uddybe, hvordan min "
                "baggrund matcher jeres behov!"
            ),
        ],
        sign_off="Med venlig hilsen,",
    )


def test_clean_full_length_en_and_da_drafts_pass_deterministic_audit() -> None:
    profile = _sample_master_profile()

    en_cl = _clean_en_cover_letter()
    en_words = sum(len(p.split()) for p in en_cl.paragraphs)
    assert 280 <= en_words <= 330

    en_result = run_deterministic_audit(_clean_en_cv(), en_cl, profile)
    assert en_result.passed is True
    assert en_result.violations == []

    da_cl = _clean_da_cover_letter()
    da_words = sum(len(p.split()) for p in da_cl.paragraphs)
    assert 280 <= da_words <= 330

    da_result = run_deterministic_audit(_clean_da_cv(), da_cl, profile)
    assert da_result.passed is True
    assert da_result.violations == []


def test_obviously_ai_draft_triggers_every_deterministic_rule_and_location() -> None:
    profile = _sample_master_profile()

    ai_cv = TailoredCV(
        language="en",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        profile_summary=(
            "Results-driven engineer who spearheaded cutting-edge platforms — delivering "
            "world-class synergy across cloud ecosystems."
        ),
        experiences=[
            CVExperience(
                company="LEGO Group",
                title="Student Developer",
                start_date="2024-06",
                end_date="2025-12",
                bullets=[
                    CVBullet(
                        lead="Backend",
                        text="Orchestrated microservices -- enabling scalable API delivery.",
                    )
                ],
            ),
            CVExperience(
                company="Fabricated AI Corp",
                title="Principal Architect",
                start_date="2023-01",
                end_date="2024-01",
                bullets=[
                    CVBullet(
                        lead="Scale",
                        text="Pioneered an internal tapestry of developer tools.",
                    )
                ],
            ),
        ],
        projects=[
            CVProject(
                name="Graph Engine",
                bullets=[
                    CVBullet(
                        lead="Launch",
                        text="Built the workflow runner in Python!",
                    )
                ],
            )
        ],
        education=[
            CVEducation(
                institution="University of Copenhagen",
                degree="BSc in Computer Science & Data Science",
                start_date="2022-09",
                end_date="2025-06",
                highlights=["Completed thesis TBD on evaluation harnesses."],
            ),
            CVEducation(
                institution="Made Up Institute of Technology",
                degree="MSc in Magic",
            ),
        ],
    )

    ai_cl = TailoredCoverLetter(
        language="en",
        full_name="Sebastian McConnell",
        email="sebastian@example.com",
        recipient_company="Nordic Cloud Systems",
        role_title="Junior Backend Engineer",
        date_str="November 22, 2026",
        greeting="Dear Hiring Team at [Company],",
        paragraphs=[
            (
                "I am writing to apply for the Junior Backend Engineer position at Nordic Cloud "
                "Systems! I'm eager to delve into your platform and hit the ground running with "
                "cutting-edge infrastructure. My recent bachelor studies in computer science and "
                "practical engineering work gave me solid exposure to Python services, automated "
                "testing, and containerized deployments across several collaborative university projects."
            ),
            (
                "During my time at LEGO Group — where I've worked with developers every day — "
                "I learned that reliability underscores every product release. Your engineering "
                "culture stands as a testament to how clarity and discipline matter, and my "
                "background plays a pivotal role in why I don't hesitate when debugging tricky "
                "distributed systems or helping teammates ship clean pull requests."
            ),
            (
                "Beyond my day job, I built evaluation pipelines (see my GitHub portfolio) that "
                "verified deterministic outputs across Python services and SQLite checkpoints. "
                "I'll always prioritize maintainable designs and clear contracts so teams can "
                "iterate quickly without breaking downstream consumers or complicating local tests."
            ),
            (
                "Thank you for reviewing my application for this exciting role at your company. "
                "I look forward to discussing how my technical foundation and collaborative habits "
                "can support your Copenhagen team in the months ahead and help you ship reliable "
                "features for customers across Europe!"
            ),
        ],
        sign_off="Best regards,",
    )

    result = run_deterministic_audit(ai_cv, ai_cl, profile)
    assert result.passed is False

    found = {(v.document, v.location, v.rule) for v in result.violations}

    # Em-dashes & double hyphens
    assert ("cv", "cv.profile_summary", "em_dash") in found
    assert ("cv", "cv.experiences[0].bullets[0]", "em_dash") in found
    assert ("cover_letter", "cover_letter.paragraph_2", "em_dash") in found

    # English contractions in cover letter only
    assert ("cover_letter", "cover_letter.paragraph_1", "english_contraction") in found
    assert ("cover_letter", "cover_letter.paragraph_2", "english_contraction") in found
    assert ("cover_letter", "cover_letter.paragraph_3", "english_contraction") in found

    # Banned AI clichés across CV and Cover Letter
    assert ("cv", "cv.profile_summary", "banned_ai_cliche") in found
    assert ("cv", "cv.experiences[0].bullets[0]", "banned_ai_cliche") in found
    assert ("cv", "cv.experiences[1].bullets[0]", "banned_ai_cliche") in found
    assert ("cover_letter", "cover_letter.paragraph_1", "banned_ai_cliche") in found
    assert ("cover_letter", "cover_letter.paragraph_2", "banned_ai_cliche") in found

    # Exclamation marks: zero in CV, zero in early cover letter paragraphs
    assert ("cv", "cv.projects[0].bullets[0]", "exclamation_mark") in found
    assert ("cover_letter", "cover_letter.paragraph_1", "exclamation_mark") in found

    # Parentheses in cover letter prose
    assert ("cover_letter", "cover_letter.paragraph_3", "parentheses_in_cover_letter") in found

    # Wrong sign-off
    assert ("cover_letter", "cover_letter.sign_off", "invalid_sign_off") in found

    # Leftover placeholder tokens
    assert ("cover_letter", "cover_letter.greeting", "placeholder_token") in found
    assert ("cv", "cv.education[0].highlights[0]", "placeholder_token") in found

    # Fabricated CV experience & education anchors
    assert ("cv", "cv.experiences[1]", "unverified_experience_anchor") in found
    assert ("cv", "cv.education[1]", "unverified_education_anchor") in found


def test_cover_letter_word_count_bounds_and_multiple_exclamations_in_final_paragraph() -> None:
    profile = _sample_master_profile()
    cv = _clean_en_cv()

    short_cl = _clean_en_cover_letter().model_copy(
        update={
            "paragraphs": [
                "First short paragraph about backend Python work.",
                "Second short paragraph about LEGO Group tooling.",
                "Third short paragraph closing warmly!",
            ]
        }
    )
    short_result = run_deterministic_audit(cv, short_cl, profile)
    assert short_result.passed is False
    short_wc = [v for v in short_result.violations if v.rule == "cover_letter_word_count"]
    assert len(short_wc) == 1
    assert short_wc[0].location == "cover_letter.paragraphs"
    assert "words" in short_wc[0].offending_snippet

    long_para = " ".join(["python"] * 110)
    long_cl = _clean_en_cover_letter().model_copy(
        update={
            "paragraphs": [
                long_para,
                long_para,
                long_para,
                f"{long_para}!",
            ]
        }
    )
    long_result = run_deterministic_audit(cv, long_cl, profile)
    assert long_result.passed is False
    long_wc = [v for v in long_result.violations if v.rule == "cover_letter_word_count"]
    assert len(long_wc) == 1
    assert long_wc[0].location == "cover_letter.paragraphs"
    assert "440 words" in long_wc[0].offending_snippet

    two_bangs_last = _clean_en_cover_letter()
    paras = list(two_bangs_last.paragraphs)
    paras[-1] = paras[-1].replace("values", "values!")
    two_bangs_cl = two_bangs_last.model_copy(update={"paragraphs": paras})
    bang_result = run_deterministic_audit(cv, two_bangs_cl, profile)
    assert bang_result.passed is False
    assert any(
        v.rule == "exclamation_mark" and v.location == "cover_letter.paragraph_4"
        for v in bang_result.violations
    )


def test_danish_sign_off_cliches_and_no_english_contraction_false_positive() -> None:
    profile = _sample_master_profile()
    da_cv = _clean_da_cv()
    da_cl = _clean_da_cover_letter()

    # Deliberately verify Danish prose with words like "it's" or similar won't fire on language="da"
    # and verify Danish clichés + wrong Danish sign-off ARE caught.
    bad_paras = list(da_cl.paragraphs)
    bad_paras[0] = (
        "Jeg skriver hermed for at søge stillingen i et dynamisk miljø med banebrydende "
        "teknologi. " + bad_paras[0]
    )
    bad_paras[1] = bad_paras[1] + " Dette spiller en afgørende rolle for vores drift."
    bad_da_cl = da_cl.model_copy(
        update={
            "paragraphs": bad_paras,
            "sign_off": "Kind Regards,",
        }
    )

    result = run_deterministic_audit(da_cv, bad_da_cl, profile)
    assert result.passed is False
    assert any(
        v.rule == "invalid_sign_off" and v.location == "cover_letter.sign_off"
        for v in result.violations
    )
    cliche_snippets = {
        v.offending_snippet.casefold()
        for v in result.violations
        if v.rule == "banned_ai_cliche"
    }
    assert "jeg skriver hermed for at søge" in cliche_snippets
    assert "dynamisk miljø" in cliche_snippets
    assert "banebrydende" in cliche_snippets
    assert "spiller en afgørende rolle" in cliche_snippets
    assert not any(v.rule == "english_contraction" for v in result.violations)


def test_session_verified_facts_allows_corrected_or_added_anchors_only() -> None:
    profile = _sample_master_profile()
    cl = _clean_en_cover_letter()

    updated_cv = _clean_en_cv().model_copy(
        update={
            "experiences": [
                CVExperience(
                    company="LEGO Group",
                    title="Backend Student Developer",
                    start_date="2024-06",
                    end_date="2026-01",
                    bullets=[
                        CVBullet(
                            lead="Tooling",
                            text="Built Python CLI tooling for ~300 engineers.",
                        )
                    ],
                ),
                CVExperience(
                    company="Aarhus AI Lab",
                    title="Research Assistant",
                    start_date="2023-09",
                    end_date="2024-05",
                    bullets=[
                        CVBullet(
                            lead="Benchmarks",
                            text="Evaluated Python data pipelines on university datasets.",
                        )
                    ],
                ),
            ],
            "education": [
                CVEducation(
                    institution="University of Copenhagen",
                    degree="BSc in Computer Science & Data Science",
                ),
                CVEducation(
                    institution="ETH Zurich",
                    degree="Exchange Semester in Computer Science",
                ),
            ],
        }
    )

    # Without session_verified_facts, both modified/added anchors and ETH Zurich fail
    unverified = run_deterministic_audit(updated_cv, cl, profile, session_verified_facts=[])
    assert unverified.passed is False
    unverified_locs = {(v.location, v.rule) for v in unverified.violations}
    assert ("cv.experiences[0]", "unverified_experience_anchor") in unverified_locs
    assert ("cv.experiences[1]", "unverified_experience_anchor") in unverified_locs
    assert ("cv.education[1]", "unverified_education_anchor") in unverified_locs

    # With session_verified_facts verifying those exact corrections/additions, audit passes
    verified_facts = [
        "Correction: At LEGO Group my title was Backend Student Developer through 2026-01.",
        "Addition: Worked at Aarhus AI Lab as Research Assistant from 2023-09 to 2024-05.",
        "Addition: Completed exchange semester at ETH Zurich.",
    ]
    verified = run_deterministic_audit(updated_cv, cl, profile, session_verified_facts=verified_facts)
    assert verified.passed is True
    assert verified.violations == []

    # Partial fact mentioning only company name must still reject an unverified fabricated title
    partial = run_deterministic_audit(
        updated_cv,
        cl,
        profile,
        session_verified_facts=["Worked at Aarhus AI Lab from 2023-09 to 2024-05."],
    )
    assert partial.passed is False
    assert any(
        v.location == "cv.experiences[1]" and v.rule == "unverified_experience_anchor"
        for v in partial.violations
    )


def test_placeholder_variants_and_contraction_possessive_boundary() -> None:
    profile = _sample_master_profile()
    cv = _clean_en_cv()
    cl = _clean_en_cover_letter()

    # Possessive apostrophes must NOT trigger the contraction rule
    possessive_paras = list(cl.paragraphs)
    possessive_paras[0] = possessive_paras[0] + " The company's engineering team's roadmap fits well."
    possessive_cl = cl.model_copy(update={"paragraphs": possessive_paras})
    possessive_res = run_deterministic_audit(cv, possessive_cl, profile)
    assert possessive_res.passed is True

    # Placeholder variants in CV and Cover Letter must all be caught
    placeholder_cv = cv.model_copy(
        update={
            "profile_summary": "Engineer targeting {{company_name}} and [[target_stack]] with TODO metrics.",
        }
    )
    placeholder_paras = list(cl.paragraphs)
    placeholder_paras[1] = placeholder_paras[1] + " Excited to join <company> as <role> at [Virksomhed] for [Role]."
    placeholder_cl = cl.model_copy(update={"paragraphs": placeholder_paras})

    ph_res = run_deterministic_audit(placeholder_cv, placeholder_cl, profile)
    assert ph_res.passed is False
    cv_tokens = {
        v.offending_snippet
        for v in ph_res.violations
        if v.rule == "placeholder_token" and v.document == "cv"
    }
    cl_tokens = {
        v.offending_snippet
        for v in ph_res.violations
        if v.rule == "placeholder_token" and v.document == "cover_letter"
    }
    assert {"{{company_name}}", "[[target_stack]]", "TODO"} <= cv_tokens
    assert {"<company>", "<role>", "[Virksomhed]", "[Role]"} <= cl_tokens


class _RecordingMockLLMClient:
    def __init__(self, result: AuditResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def invoke_structured(
        self,
        tier: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[AuditResult],
    ) -> AuditResult:
        self.calls.append(
            {
                "tier": tier,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema": schema,
            }
        )
        return self._result


def test_run_llm_audit_uses_reasoning_tier_auditor_prompt_and_audit_result_schema() -> None:
    profile = _sample_master_profile()
    cv = _clean_en_cv()
    cl = _clean_en_cover_letter()
    expected = AuditResult(
        passed=False,
        violations=[
            AuditViolation(
                document="cover_letter",
                location="cover_letter.paragraph_2",
                rule="humanizer_ing_trailer",
                offending_snippet="enabling teams to thrive",
                fix_instruction="Replace the vague -ing trailer with a concrete outcome.",
            )
        ],
    )
    mock_client = _RecordingMockLLMClient(expected)

    result = run_llm_audit(
        cv=cv,
        cover_letter=cl,
        major_gaps=["Embedded C++"],
        profile=profile,
        session_verified_facts=["User confirmed Pulumi IaC experience."],
        llm_client=mock_client,  # type: ignore[arg-type]
    )

    assert result == expected
    assert len(mock_client.calls) == 1
    call = mock_client.calls[0]
    assert call["tier"] == "reasoning"
    assert call["system_prompt"] == get_prompt("auditor")
    assert call["schema"] is AuditResult

    # Verify all required inputs are serialized into the user prompt
    json_blob = call["user_prompt"].split("\n\n", 1)[1]
    payload = json.loads(json_blob)
    assert payload["cv"]["full_name"] == "Sebastian McConnell"
    assert payload["cover_letter"]["recipient_company"] == "Nordic Cloud Systems"
    assert payload["major_gaps"] == ["Embedded C++"]
    assert payload["master_profile"]["identity"]["email"] == "sebastian@example.com"
    assert payload["session_verified_facts"] == ["User confirmed Pulumi IaC experience."]
