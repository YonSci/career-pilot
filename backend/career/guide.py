"""Job seeker's guide: short, practical articles for data, climate, geospatial,
agriculture and development careers, written for Ethiopia-based and remote
candidates. Rendered as public pages (search traffic) that end with the tool."""

ARTICLES = [
    {
        "slug": "finding-roles",
        "title": "Where the good roles are, and how to catch them early",
        "summary": "Most data, climate and development vacancies never reach LinkedIn's feed. Here is where they appear first and how to watch those places without checking ten sites a day.",
        "minutes": 5,
        "body": """
<h2>Where postings appear first</h2>
<p>For development-sector work the order is usually: the employer's own careers page, then ReliefWeb, then aggregators, then LinkedIn a few days later. Consultancies and research positions are often on ReliefWeb and nowhere else. Tech-adjacent roles at NGOs and research centres tend to sit on applicant-tracking boards (Greenhouse, Lever, Workable, SmartRecruiters) that job sites only pick up slowly.</p>
<p>Practical consequence: if you only watch LinkedIn, you see many roles after the strongest candidates have already applied, and you miss consultancies entirely.</p>
<h2>Build a watch list, not a habit</h2>
<ol>
<li><strong>ReliefWeb searches</strong> for your keywords (for example "data", "GIS", "hydrology", "MEL") and for your location. Save the search and its RSS feed.</li>
<li><strong>Ten employers you would actually join.</strong> Find their careers page and note whether it runs on Greenhouse, Lever, Workable or SmartRecruiters. Those can be followed directly.</li>
<li><strong>Alert emails</strong> from LinkedIn, Devex, UNjobs and Impactpool, routed to one mailbox label so they stop cluttering your inbox.</li>
<li><strong>A Telegram channel</strong> that posts new roles in your field daily, so a glance on the phone replaces a morning of browsing.</li>
</ol>
<h2>Read the closing date first</h2>
<p>Many NGO vacancies close within ten days, and consultancies sometimes within five. Sort by closing date, not posting date, when you are deciding what to do this week. A strong application to a role closing on Friday beats three rushed ones next month.</p>
<h2>Do not skip the "unknowns"</h2>
<p>Postings often list requirements you cannot judge from the outside: citizenship, a specific licence, "based in" clauses. Note them explicitly instead of hoping. If a mandatory requirement is unknown, ask the contact address before investing a day in the application.</p>
""",
    },
    {
        "slug": "cv-that-survives-screening",
        "title": "A CV that survives the first screening",
        "summary": "Screening is done in seconds, by people and increasingly by software. What gets a data or climate CV through, and what quietly disqualifies it.",
        "minutes": 6,
        "body": """
<h2>Lead with verifiable facts</h2>
<p>The first third of the page decides everything. Open with a three-line summary that states your field, your years of experience, and two concrete results: "Built the seasonal forecast pipeline used by X for 2024 planning", "Delivered dashboards used across 4 country programmes". Claims that a reader could check are worth more than adjectives.</p>
<h2>Quantify, then name the tools</h2>
<p>Every role bullet should carry a number where one exists: stations covered, records processed, users served, budget managed, improvement measured. Follow the number with the tools, using the exact names employers search for: Python, R, SQL, QGIS, ArcGIS, Google Earth Engine, Power BI, Stata, WRF, CHIRPS. Recruiters filter on these words.</p>
<h2>Match the posting's vocabulary</h2>
<p>If the posting says "monitoring, evaluation and learning", do not write "M&E" only. If it says "geospatial", say geospatial, not just "maps". Software screening looks for the posting's own words; human screeners do the same unconsciously.</p>
<h2>Keep it to two pages</h2>
<p>Two pages for most professionals, three for senior researchers with long publication lists. Put publications and trainings in a compact final section; put languages with a level (working, fluent, native) because development employers care.</p>
<h2>Remove what invites doubt</h2>
<ul>
<li>Photos, date of birth, marital status: unnecessary for international employers.</li>
<li>Unexplained gaps: one honest line ("2022: full-time study") is better than silence.</li>
<li>Skills you cannot demonstrate in an interview: they become the question you fail.</li>
</ul>
<h2>Keep a master version</h2>
<p>Maintain one long master CV with every fact, and cut a tailored two-page version per application. Tools that check each claim against your master evidence catch the mistake where a rushed tailored CV says something the master never did.</p>
""",
    },
    {
        "slug": "applying-to-ngos-and-un-agencies",
        "title": "Applying to NGOs, UN agencies and research centres",
        "summary": "Grades, cover letters, competency frameworks and referees: the parts of a development-sector application that differ from a private-sector one.",
        "minutes": 7,
        "body": """
<h2>Understand grades before you apply</h2>
<p>UN agencies advertise by grade (G for general service, NO for national officers, P for international professionals). NO-A and NO-B suit early-career nationals; P-2 and P-3 need several years and usually a master's degree. International NGOs use their own bands but the pattern is the same: an "Officer" role, a "Specialist" or "Manager", then "Advisor" or "Lead". Applying two levels up wastes everyone's time; one level up is normal.</p>
<h2>The cover letter answers three questions</h2>
<ol>
<li>Why this organisation and this role, in one specific sentence that shows you read the posting.</li>
<li>The two or three requirements you meet best, with the evidence, in the posting's own order.</li>
<li>What you know you do not yet have, and how you would close it. Honesty here is remembered.</li>
</ol>
<p>Keep it to one page. Address the requirements list directly; hiring panels score against it.</p>
<h2>Competency frameworks are literal</h2>
<p>Many organisations score on named competencies (for example "Delivering results", "Working with others"). Your examples should be labelled with them. Use one paragraph per competency: the situation, what you did, what happened.</p>
<h2>Consultancies are a different game</h2>
<p>A consultancy call wants a short technical proposal: your understanding of the task, the method, a timeline, a daily rate, and past assignments that resemble it. Eligibility often requires a registered entity or a team; check that before writing.</p>
<h2>Referees and portfolios</h2>
<p>Line up three referees who have seen your work and warn them each time you apply. For data and geospatial roles, a public portfolio (a GitHub repository, a dashboard, a map, a short report) does more than any adjective in the CV. Link it.</p>
""",
    },
    {
        "slug": "interviews-for-data-and-climate-roles",
        "title": "Interviews for data, GIS and climate roles",
        "summary": "Competency questions, technical tests and the questions you should ask. How to prepare in a week.",
        "minutes": 6,
        "body": """
<h2>Expect two kinds of questions</h2>
<p>Development-sector panels ask <strong>competency</strong> questions ("Tell us about a time you had to deliver with incomplete data") and <strong>technical</strong> questions ("How would you validate a satellite rainfall product for this basin?"). Prepare both. For each requirement in the posting, have one story and one method ready.</p>
<h2>Tell stories with the STAR shape</h2>
<p>Situation, task, action, result, in under two minutes. Panels take notes against a rubric; a clear structure lets them score you. End every story with the result and, if you can, a number.</p>
<h2>Technical tests</h2>
<p>Data roles often include a take-home exercise: clean a dataset, build a chart, explain a choice. Time-box it, document your assumptions in a short readme, and prefer a correct simple method over an impressive incomplete one. GIS roles may ask for a map from provided layers; climate roles for an explanation of an index or a forecast product. Practise explaining your daily tools to a non-specialist.</p>
<h2>Research the organisation properly</h2>
<p>Read the latest annual report, the country strategy, and any evaluation of the programme you would join. Panels notice when a candidate references a real project. It also tells you whether you want the job.</p>
<h2>Ask questions that show judgement</h2>
<ul>
<li>"What does the first six months need to deliver?"</li>
<li>"Which data sources does the team rely on, and which do you distrust?"</li>
<li>"How is this role funded, and until when?"</li>
</ul>
<p>The last one is fair and important in a grant-funded sector.</p>
""",
    },
    {
        "slug": "running-your-search-with-jobs-find-ai",
        "title": "Running your search with Jobs Find AI",
        "summary": "How members use the tool day to day: verify the CV once, follow the right sources, read the match explanations, and draft applications that only claim what you can prove.",
        "minutes": 4,
        "body": """
<h2>1. Verify your evidence once</h2>
<p>Upload your CV. The tool extracts each fact with the exact quote it came from and asks you to verify it. Only verified facts are ever used, so this ten-minute step is what makes every later match and draft trustworthy.</p>
<h2>2. Follow sources, not job sites</h2>
<p>Add the suggested ReliefWeb searches and employer boards for your field, or connect a mailbox label that collects your LinkedIn, Devex and UNjobs alert emails. The tool reads these continuously.</p>
<h2>3. Read the explanation, not just the score</h2>
<p>Each posting gets a relevance score and a requirement-by-requirement table: met, partly met, unknown or missing, each pointing to the evidence. "Unknown" is deliberate: if the posting demands a citizenship or a licence that your CV does not mention, the tool never assumes it.</p>
<h2>4. Get alerts where you already look</h2>
<p>Link Telegram under Account, or use email. Alerts only go out for matches above your threshold, so the channel stays quiet unless something is worth your time.</p>
<h2>5. Draft, then make it yours</h2>
<p>Press "Prepare application" on a role you want. The tool drafts a tailored CV, cover letter and screening answers, every claim tied to a verified fact, reviewed once for accuracy. You edit, export and submit through the employer's own channel. Nothing is ever sent on your behalf.</p>
<h2>Weekly rhythm that works</h2>
<p>Monday: check the closing-soon list. Midweek: review new matches and skip the irrelevant ones so the tool learns your preferences. Friday: prepare one or two applications properly rather than five in a hurry.</p>
""",
    },
]


def by_slug(slug):
    return next((a for a in ARTICLES if a["slug"] == slug), None)
