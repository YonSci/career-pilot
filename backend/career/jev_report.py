"""Compare JEV scores with LLM evaluations and members' decisions, to judge
whether rank mode would drop good postings. Read-only.

    python -m career.jev_report          (on Render: Shell tab, from /app)
"""

from .config import settings
from .db import Session, Record, read
from .schemas import Preferences


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2
        i = j + 1
    return result


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    var = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return cov / var if var else None


# The cutoff sweep counts postings at or above this LLM score as good matches,
# independent of members' own minimum scores (which few postings reach).
GOOD_LLM_SCORE = 60
SWEEP_CUTOFFS = (20, 25, 30, 35, 40)


def kept(jev, cutoff=None):
    """Whether rank mode would still send this posting to the LLM."""
    cutoff = settings.jev_min_score if cutoff is None else cutoff
    return jev["score"] >= cutoff or jev["confidence"] < settings.jev_confident


def main():
    totals = {"scored": 0, "tokens": 0, "kept": 0, "strong": 0, "strong_kept": 0, "chosen": 0, "chosen_kept": 0, "skipped": 0, "skipped_dropped": 0}
    jev_scores, llm_scores = [], []
    scored, good = [], []
    with Session() as db:
        jobs = db.query(Record).filter_by(kind="job").all()
        min_scores = {}
        for row in jobs:
            jev = row.data.get("jev")
            if not jev:
                continue
            if row.user_id not in min_scores:
                prefs = {**Preferences().model_dump(), **(read(db, "preferences", {}, user_id=row.user_id) or {})}
                min_scores[row.user_id] = prefs["min_score"]
            totals["scored"] += 1
            totals["tokens"] += jev.get("tokens") or 0
            totals["kept"] += kept(jev)
            scored.append(jev)
            match = row.data.get("match") or {}
            if match.get("mode") == "ai":
                jev_scores.append(jev["score"])
                llm_scores.append(match["score"])
                if match["score"] >= GOOD_LLM_SCORE:
                    good.append(jev)
                if match["score"] >= min_scores[row.user_id]:
                    totals["strong"] += 1
                    totals["strong_kept"] += kept(jev)
            status = row.data.get("status")
            if status in ("saved", "applied"):
                totals["chosen"] += 1
                totals["chosen_kept"] += kept(jev)
            elif status == "skipped":
                totals["skipped"] += 1
                totals["skipped_dropped"] += not kept(jev)

    def share(part, whole):
        return f"{part}/{whole} ({100 * part / whole:.0f}%)" if whole else "n/a"

    rho = spearman(jev_scores, llm_scores)
    print(f"Thresholds: JEV_MIN_SCORE={settings.jev_min_score}, JEV_CONFIDENT={settings.jev_confident}")
    print(f"Postings with a JEV score: {totals['scored']}, input tokens {totals['tokens']}")
    print(f"Rank mode would send to the LLM: {share(totals['kept'], totals['scored'])}")
    print(f"Postings with both scores: {len(jev_scores)}; rank correlation (Spearman): {'n/a' if rho is None else f'{rho:.2f}'}")
    print(f"LLM-strong matches (>= each member's minimum score) kept: {share(totals['strong_kept'], totals['strong'])}")
    print(f"Saved or applied postings kept: {share(totals['chosen_kept'], totals['chosen'])}")
    print(f"Skipped postings JEV would drop: {share(totals['skipped_dropped'], totals['skipped'])}")
    print(f"Cutoff sweep (good match = LLM score >= {GOOD_LLM_SCORE}; JEV_CONFIDENT unchanged):")
    for cut in sorted({*SWEEP_CUTOFFS, settings.jev_min_score}):
        sends = share(sum(kept(j, cut) for j in scored), len(scored))
        keeps = share(sum(kept(j, cut) for j in good), len(good))
        current = " (current)" if cut == settings.jev_min_score else ""
        print(f"  JEV_MIN_SCORE={cut}: sends {sends}, keeps {keeps} good matches{current}")
    print("Target before switching to rank mode: at least 95% of strong and of saved/applied postings kept.")


if __name__ == "__main__":
    main()
