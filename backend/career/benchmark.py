"""Blind relevance labels for validating JEV and the LLM evaluation.

The owner labels a sample of their own JEV-scored jobs as relevant to their CV
or not, without seeing any score, in the Cohort tab. jev_report then measures
against these labels how many relevant jobs rank mode would keep and the LLM
rates as good. The labels are independent of both models, though they are one
person's judgement. Only the owner's own jobs are used: judging fit needs the
CV, and members' CVs stay private.
"""

import random
from .db import now, put, rows
from . import jev as scoring

SAMPLE_SIZE = 60
# Equal shares from low, middle and high JEV scores, so misses among low scores show up.
BANDS = ((0, 40), (40, 70), (70, 101))


def _scored(row):
    jev = row.data.get("jev") or {}
    return jev.get("rubric") == scoring.RUBRIC_VERSION and not row.data.get("keyword_sample")


def draw(db):
    """Top the scoped account's sample up to SAMPLE_SIZE from its current JEV scores."""
    jobs = [r for r in rows(db, "job") if _scored(r)]
    sampled = [r for r in jobs if r.data.get("benchmark")]
    for low, high in BANDS:
        band = [r for r in jobs if low <= r.data["jev"]["score"] < high]
        wanted = SAMPLE_SIZE // len(BANDS) - sum(1 for r in band if r.data.get("benchmark"))
        pool = [r for r in band if not r.data.get("benchmark")]
        for r in random.sample(pool, max(0, min(wanted, len(pool)))):
            put(db, "job", r.key, {**r.data, "benchmark": {"sampled": now()}})
            sampled.append(r)
    return sampled


def progress(db):
    sampled = [r.data["benchmark"] for r in rows(db, "job") if r.data.get("benchmark")]
    return {
        "size": SAMPLE_SIZE,
        "sampled": len(sampled),
        "labelled": sum(1 for b in sampled if "relevant" in b),
        "relevant": sum(1 for b in sampled if b.get("relevant") is True),
        "unsure": sum(1 for b in sampled if b.get("unsure")),
    }


def next_job(db):
    """The next unlabelled job of the sample, without any score."""
    waiting = [r for r in draw(db) if "relevant" not in r.data["benchmark"] and not r.data["benchmark"].get("unsure")]
    if not waiting:
        return None
    r = min(waiting, key=lambda r: r.data["benchmark"]["sampled"] + r.key)
    return {
        "id": r.id,
        **{k: r.data.get(k) for k in ("title", "company", "location", "url", "deadline")},
        "description": (r.data.get("description") or "")[:8000],
    }


def label(db, row, relevant):
    """relevant: True, False, or None when the owner cannot judge."""
    mark = {**row.data["benchmark"], "labelled": now()}
    if relevant is None:
        mark["unsure"] = True
    else:
        mark["relevant"] = relevant
    put(db, "job", row.key, {**row.data, "benchmark": mark})
