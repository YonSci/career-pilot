"""Compare JEV scores with LLM evaluations and members' decisions, to judge
whether rank mode would drop good postings. Read-only.

    python -m career.jev_report          (on Render: Shell tab, from /app)
"""

from .config import settings
from .db import Session, Record, read
from .schemas import Preferences
from .jev import held


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


def kept(jev, job, cutoff=None):
    """Whether rank mode would still send this posting to the LLM."""
    return not held(jev, job, cutoff)


def wilson(part, whole, z=1.96):
    """95% Wilson interval for a share: how uncertain a small sample still is."""
    p = part / whole
    denom = 1 + z * z / whole
    centre = (p + z * z / (2 * whole)) / denom
    half = z * ((p * (1 - p) + z * z / (4 * whole)) / whole) ** 0.5 / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def share(part, whole, interval=False):
    if not whole:
        return "n/a"
    text = f"{part}/{whole} ({100 * part / whole:.0f}%"
    if interval:
        low, high = wilson(part, whole)
        text += f", 95% interval {100 * low:.0f}-{100 * high:.0f}%"
    return text + ")"


def main():
    # scored: every JEV-scored posting. evaluated: also evaluated by the LLM in
    # the normal queue. sampled: evaluated because the random sample of postings
    # rank mode would hold picked it; kept apart because it was not chosen by keywords.
    scored, evaluated, sampled, decided = [], [], [], []
    tokens = 0
    with Session() as db:
        min_scores = {}
        for row in db.query(Record).filter_by(kind="job").all():
            jev = row.data.get("jev")
            if not jev:
                continue
            if row.user_id not in min_scores:
                prefs = {**Preferences().model_dump(), **(read(db, "preferences", {}, user_id=row.user_id) or {})}
                min_scores[row.user_id] = prefs["min_score"]
            tokens += jev.get("tokens") or 0
            scored.append((jev, row.data))
            match = row.data.get("match") or {}
            if match.get("mode") == "ai":
                entry = (jev, row.data, match["score"], min_scores[row.user_id])
                (sampled if jev.get("sample") else evaluated).append(entry)
            if row.data.get("status") in ("saved", "applied", "skipped"):
                decided.append((jev, row.data))

    def count(items, test):
        return sum(1 for item in items if test(item))

    strong = [e for e in evaluated if e[2] >= e[3]]
    good = [e for e in evaluated if e[2] >= GOOD_LLM_SCORE]
    chosen = [d for d in decided if d[1]["status"] in ("saved", "applied")]
    skipped = [d for d in decided if d[1]["status"] == "skipped"]
    rho = spearman([e[0]["score"] for e in evaluated], [e[2] for e in evaluated])

    print(f"Thresholds: JEV_MIN_SCORE={settings.jev_min_score}, JEV_CONFIDENT={settings.jev_confident}")
    print(f"Postings with a JEV score: {len(scored)}, input tokens {tokens}")
    print(f"Rank mode would send to the LLM: {share(count(scored, lambda s: kept(*s)), len(scored))} of all scored postings")
    print(f"Evaluated by the LLM in the normal queue: {len(evaluated)}; rank correlation (Spearman): {'n/a' if rho is None else f'{rho:.2f}'}")
    print(f"LLM-strong matches (>= each member's minimum score) kept: {share(count(strong, lambda e: kept(e[0], e[1])), len(strong), True)}")
    print(f"Saved or applied postings kept: {share(count(chosen, lambda d: kept(*d)), len(chosen), True)}")
    print(f"Skipped postings JEV would drop: {share(count(skipped, lambda d: not kept(*d)), len(skipped))}")

    # Only the random sample shows what JEV would miss among postings the normal
    # queue never sent to the LLM. Sampled under an older cutoff counts only if still held.
    still_held = [e for e in sampled if held(e[0], e[1])]
    sample_good = count(still_held, lambda e: e[2] >= GOOD_LLM_SCORE)
    print(f"Random sample of postings rank mode would hold, evaluated by the LLM: {len(still_held)}")
    if still_held:
        held_total = count(scored, lambda s: held(*s))
        rate = sample_good / len(still_held)
        print(f"  good matches among them: {share(sample_good, len(still_held), True)}; "
              f"about {rate * held_total:.0f} of the {held_total} held postings may be good matches")

    print(f"Cutoff sweep (good match = LLM score >= {GOOD_LLM_SCORE} in the normal queue; JEV_CONFIDENT unchanged):")
    for cut in sorted({*SWEEP_CUTOFFS, settings.jev_min_score}):
        sends_all = share(count(scored, lambda s: kept(s[0], s[1], cut)), len(scored))
        sends_evaluated = share(count(evaluated, lambda e: kept(e[0], e[1], cut)), len(evaluated))
        keeps = share(count(good, lambda e: kept(e[0], e[1], cut)), len(good))
        current = " (current)" if cut == settings.jev_min_score else ""
        print(f"  JEV_MIN_SCORE={cut}: sends {sends_all} of all scored, {sends_evaluated} of evaluated; keeps {keeps} good matches{current}")
    print("Target before switching to rank mode: at least 95% of strong and of saved/applied postings kept,")
    print("with few good matches in the random sample. Small samples leave wide intervals; read them, not just the share.")


if __name__ == "__main__":
    main()
