import pytest
from career.config import settings
from career.ai import extract_profile, match_job, write_package
from career.schemas import Profile, Fact, Match, Requirement, Package, QualityReview


def test_untraceable_extracted_facts_are_rejected(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    output = Profile(
        facts=[
            Fact(
                id="F1",
                category="degree",
                text="PhD",
                source_quote="invented source",
                verified=True,
            )
        ]
    )
    monkeypatch.setattr("career.ai.structured", lambda *a: output)
    with pytest.raises(ValueError, match="source-grounded"):
        extract_profile("Python developer with extensive climate modelling experience.")


def test_met_requirement_without_real_evidence_becomes_unknown(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    output = Match(
        score=90,
        summary="Example",
        requirements=[
            Requirement(
                requirement="Doctorate",
                mandatory=True,
                status="met",
                evidence_ids=["F999"],
                reason="Guessed",
            )
        ],
        strengths=[],
        gaps=[],
    )
    monkeypatch.setattr("career.ai.structured", lambda *a: output)
    result = match_job(
        {"facts": [{"id": "F1", "text": "Python developer", "verified": True}]},
        {"title": "Scientist"},
        {},
    )
    assert result["requirements"][0]["status"] == "unknown"


def test_independent_review_blocks_unsupported_claims(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "fake")
    data = {
        "cv": {
            "title": "CV",
            "paragraphs": [
                {"text": "Invented a new satellite.", "evidence_ids": ["F1"]}
            ],
        },
        "cover_letter": {"title": "Letter", "paragraphs": []},
        "answers": [],
        "additional_documents": [],
        "checklist": [],
        "missing_information": [],
    }

    def structured(model, schema, *args):
        return (
            Package(**data)
            if schema is Package
            else QualityReview(
                unsupported_claims=["Invented satellite achievement."],
                missing_requirements=[],
            )
        )

    monkeypatch.setattr("career.ai.structured", structured)
    with pytest.raises(ValueError, match="unsupported claims"):
        write_package(
            {"facts": [{"id": "F1", "text": "Used satellite data.", "verified": True}]},
            {"title": "Scientist"},
            {},
        )
