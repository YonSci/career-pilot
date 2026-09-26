from typing import Literal
from pydantic import BaseModel, Field


class Fact(BaseModel):
    id: str
    category: str
    text: str
    source_quote: str
    verified: bool = False


class Profile(BaseModel):
    name: str = ""
    headline: str = ""
    facts: list[Fact] = Field(default_factory=list, max_length=300)


class Preferences(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: [
            "data science",
            "machine learning",
            "climate",
            "geospatial",
            "hydrology",
            "remote sensing",
            "digital agriculture",
        ]
    )
    locations: list[str] = Field(
        default_factory=lambda: ["Ethiopia", "Remote", "Africa"]
    )
    contract_types: list[str] = Field(
        default_factory=lambda: ["Consultancy", "Full-time"]
    )
    excluded_keywords: list[str] = Field(default_factory=list)
    min_score: int = Field(default=70, ge=0, le=100)
    notify_channels: list[Literal["email", "telegram", "whatsapp", "push"]] = Field(
        default_factory=list
    )
    alerts_enabled: bool = False
    max_alerts_per_run: int = Field(default=10, ge=1, le=30)
    # "each" sends one message per job; "digest" sends one summary per run.
    alert_mode: Literal["each", "digest"] = "each"
    # Email is bundled into one summary per search regardless of alert_mode.
    email_digest: bool = True
    # "soft" ranks preferred locations first; "strict" drops other locations.
    location_mode: Literal["soft", "strict"] = "soft"
    scan_interval_hours: int = Field(default=6, ge=1, le=48)


# Fields that change what the matching model sees. Other preferences never
# invalidate stored evaluations.
MATCH_RELEVANT_PREFERENCES = ("keywords", "locations", "contract_types")


class JobInput(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    company: str = Field(default="", max_length=240)
    location: str = Field(default="Not specified", max_length=240)
    description: str = Field(min_length=30, max_length=60000)
    url: str = Field(default="", max_length=2000)
    deadline: str | None = None
    posted: str | None = None
    source: str = "Manual"
    external_id: str = ""


class Requirement(BaseModel):
    requirement: str
    mandatory: bool
    status: Literal["met", "not_met", "unknown"]
    evidence_ids: list[str]
    reason: str


class Match(BaseModel):
    score: int = Field(ge=0, le=100)
    summary: str
    requirements: list[Requirement]
    strengths: list[str]
    gaps: list[str]
    mode: str = "ai"


class Paragraph(BaseModel):
    text: str
    evidence_ids: list[str]


class DraftDocument(BaseModel):
    title: str
    paragraphs: list[Paragraph]


class Answer(BaseModel):
    question: str
    answer: str
    evidence_ids: list[str]
    character_limit: int | None


class Package(BaseModel):
    cv: DraftDocument
    cover_letter: DraftDocument
    answers: list[Answer]
    additional_documents: list[DraftDocument]
    checklist: list[str]
    missing_information: list[str]


class QualityReview(BaseModel):
    unsupported_claims: list[str]
    missing_requirements: list[str]


SourceKind = Literal[
    "greenhouse",
    "lever",
    "reliefweb",
    "gmail",
    "imap",
    "rss",
    "page",
    "workable",
    "smartrecruiters",
    "ashby",
    "remotive",
]


class SourceInput(BaseModel):
    kind: SourceKind
    value: str = Field(default="", max_length=500)
    enabled: bool = True
