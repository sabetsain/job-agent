# Document of Intent: Autonomous Job-Hunting & Application Co-Pilot

## 1. Purpose
Build a personal job-hunting co-pilot that continuously discovers relevant roles, prepares truthful and well-crafted application materials tailored to each opportunity, collaborates with me conversationally to ideate and refine them, and keeps my applications, documents, and interviews organized from discovery through offer.

## 2. Guiding Principles
- **Co-Pilot, Not Auto-Applier:** The assistant does the heavy lifting — discovering roles, tailoring documents, highlighting gaps, and organizing files — while I stay in control of review, revision, and final submission. No brittle automated form-filling or workarounds around application portals.
- **Strict Truthfulness & Smart Transferability (Zero Fabrication):** Tailored CVs and cover letters may select, reorder, rephrase, and faithfully translate facts from my verified Master Profile, but must never invent or inflate skills, metrics, titles, dates, or experiences. When a role asks for something not explicitly in my profile:
  1. **Surface related experience first:** Highlight transferable or adjacent experience from my profile where relevant (for example, noting Infrastructure-as-Code experience with Pulumi when a role mentions Terraform).
  2. **Flag only major gaps:** Still produce the tailored CV and cover letter, and alongside them call out only the *major* unaddressed gaps (avoiding noisy nitpicks over minor or secondary tools). From there, I can decide whether the drafts are good enough as-is or share relevant experience I do have so the co-pilot can revise.
- **Authenticity & Personal Voice:** Application materials should read like me, not generic generated prose. Cover letters and summaries are guided by a personal voice profile modeled on my own writing.
- **Design Integrity:** CVs and cover letters must remain clean, readable, and easy for hiring systems and humans to scan. Fitting within page limits must always be achieved by editing and tightening content — never by shrinking text below a readable minimum (9pt) or sacrificing whitespace and layout balance.
- **Bilingual Fluency:** Because I am fluent in both Danish and English and targeting Denmark, every application is matched to the language of the job posting — Danish postings receive Danish CVs and cover letters; English postings receive English ones.

## 3. What Makes a Role Worth Pursuing
- **Primary Target:** Entry-level roles.
- **Location & Work Mode:** Focused on Copenhagen, Denmark (and Europe) as well as Remote roles compatible with European working hours.
- **Posting Freshness & Daily Focus:** Roles posted more than ~2–3 weeks ago are filtered out (unless an explicit future application deadline is listed). The co-pilot still evaluates all eligible postings, but caps drafting to **at most 3 applications per day** (an upper cap, never a quota — if fewer or zero roles qualify, only those are drafted) — prioritizing un-drafted roles posted within the last 7 days or carrying an active future application deadline, and only falling back to older eligible roles when no preferred-window roles remain.
- **Compensation:** Not a filtering criterion — as long as location, seniority, and skill/domain fit align, compensation does not disqualify a role.
- **Seniority & Skill Eligibility:**
  - **Senior and Above:** Never pursued. Any role at Senior, Staff, Principal, Lead, Manager, or above is automatically excluded.
  - **Entry-Level Roles:** My primary focus; broadly worth considering, with slight flexibility on must-have skill coverage.
  - **Early Stretch Roles (~2 years required):** Considered if and only if my must-have skill coverage is maximized.
- **Domain & Nice-to-Haves:** Open to a wide variety of industries and problem spaces; nice-to-have skills and growth opportunities serve as positive signals rather than hard gates.
- **Dealbreakers:** Excluded companies, industries, contract types, or red-flag criteria are always respected upfront.

## 4. How Opportunities Are Found
- **Whitelisted Discovery Boards:** Focus on broad discovery across curated, openly accessible job boards relevant to Copenhagen, Europe, and Remote roles — rather than maintaining a narrow watchlist of specific companies or relying on sparse email alerts.
- **Ad-Hoc Additions:** I can also drop in any role I come across myself (from a recruiter, friend, or job board) to put it through the exact same evaluation and tailoring workflow. If a link cannot be accessed or parsed (for example, behind a login wall or blocked), the co-pilot fails loudly and explains why so I know immediately.

## 5. Core Co-Pilot Workflows

### A. Discovery, Tailoring & Conversational Ideation (Daily)
1. **Find & Filter:** Pull new roles from whitelisted discovery boards, skip roles already seen, and immediately filter out postings that violate location, freshness, seniority, or dealbreaker rules.
2. **Evaluate Fit:** Assess remaining roles against my Master Profile and tiered seniority/skill criteria so only genuinely strong matches move forward, prioritizing fresher postings.
3. **Prepare & Verify:** Draft a tailored CV and cover letter in the posting's language — surfacing transferable skills, auditing strictly against my Master Profile, voice guidelines, and layout standards, and noting any major unaddressed gaps.
4. **Ideate, Revise & Approve in Slack:** Each matched role opens its own dedicated thread in Slack with a concise job brief, fit breakdown, major gaps (if any), direct application link, and the tailored documents.
   - The thread supports open back-and-forth ideation (discussing gaps, angles, or additional experience I want to bring in) without forcing a full rewrite on every reply.
   - Only when I explicitly instruct the co-pilot to **re-iterate** does it regenerate and post updated documents in the thread.
   - Only when I explicitly **approve** (or dismiss) the role does the workflow conclude — finalizing the tracker and archiving the exact submitted versions.

### B. Inbox Monitoring & Interview Sync (Hourly)
1. **Watch for Replies:** Check incoming emails related to active applications.
2. **Understand & Track:** Identify interview invitations, assessments, rejections, or other updates and keep the application tracker current.
3. **Prepare for Interviews:** When an interview invite arrives, message me in Slack with the exact tailored CV and cover letter PDFs tied to that application (so I immediately remember what I applied with), and create a calendar event with the interview details.

### D. Lightweight Data Hygiene
- Roles ingested more than 6 months ago are automatically cleared out to keep the tracker clean, except any role currently marked as interviewing (`interview in process`), which is always kept.

### C. Weekly Profile Check-In (Weekly)
1. **Prompt:** Every Sunday, the co-pilot asks a brief question in Slack about what I shipped, learned, or accomplished that week.
2. **Capture:** I reply in plain text; the co-pilot distills concrete accomplishments, metrics, and skills, asks for quick confirmation, and updates my Master Profile so it stays continuously up to date.
