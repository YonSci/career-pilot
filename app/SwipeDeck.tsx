"use client";
import { useRef, useState } from "react";
import { ArrowUpRight, Bookmark, RotateCcw, X } from "lucide-react";
import type { Job } from "./page";

const SWIPE = 110;

// One posting at a time: swipe (or press) right to shortlist, left to skip.
export default function SwipeDeck({
  jobs,
  minScore,
  decide,
  open,
}: {
  jobs: Job[];
  minScore: number;
  decide: (j: Job, status: string) => void;
  open: (id: string) => void;
}) {
  const [done, setDone] = useState<string[]>([]),
    [last, setLast] = useState<null | { job: Job; from: string }>(null),
    [dx, setDx] = useState(0),
    start = useRef<number | null>(null);
  const deck = jobs.filter((j) => !done.includes(j.id)),
    top = deck[0];
  const commit = (status: string) => {
    if (!top) return;
    setDone((d) => [...d, top.id]);
    setLast({ job: top, from: top.status });
    setDx(0);
    decide(top, status);
  };
  const undo = () => {
    if (!last) return;
    setDone((d) => d.filter((id) => id !== last.job.id));
    decide(last.job, last.from);
    setLast(null);
  };
  const undoButton = last && (
    <button className="text-button" onClick={undo}>
      <RotateCcw size={15} /> Undo {last.job.title.length > 40 ? last.job.title.slice(0, 40) + "…" : last.job.title}
    </button>
  );
  if (!top)
    return (
      <div className="empty-jobs">
        <h2>{done.length ? "You have been through every job in this view." : "No jobs to decide on here."}</h2>
        <p>Cards show the jobs you have not shortlisted or skipped yet, with your filters applied.</p>
        {undoButton}
      </div>
    );
  const f = top.facts;
  return (
    <div
      className="swipe-deck"
      tabIndex={0}
      aria-label="Job cards. Right arrow shortlists, left arrow skips."
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") commit("saved");
        if (e.key === "ArrowLeft") commit("skipped");
      }}
    >
      <p className="muted-text">
        {deck.length} to go · swipe right to shortlist, left to skip
      </p>
      <article
        className="job-card swipe-card"
        style={{ transform: `translateX(${dx}px) rotate(${dx / 25}deg)`, transition: start.current == null ? "transform .2s" : "none" }}
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest("button")) return;
          start.current = e.clientX;
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => start.current != null && setDx(e.clientX - start.current)}
        onPointerUp={() => {
          start.current = null;
          if (dx > SWIPE) commit("saved");
          else if (dx < -SWIPE) commit("skipped");
          else setDx(0);
        }}
        onPointerCancel={() => {
          start.current = null;
          setDx(0);
        }}
      >
        <span className="swipe-hint save" style={{ opacity: Math.max(0, dx / SWIPE) }}>
          Shortlist
        </span>
        <span className="swipe-hint skip" style={{ opacity: Math.max(0, -dx / SWIPE) }}>
          Skip
        </span>
        <div className="job-top">
          <div className="job-identity">
            <span className="company-name">{top.company || "Employer not specified"}</span>
            <strong className="swipe-title">{top.title}</strong>
          </div>
          <span className={"score " + (top.match && top.match.score >= minScore ? "high" : "")}>
            {top.match ? (
              <>
                <strong>{top.match.score}</strong>
                <small>MATCH</small>
              </>
            ) : (
              <small>UNRANKED</small>
            )}
          </span>
        </div>
        <div className="job-meta">
          <span>{top.location}</span>
          <span>{top.source}</span>
        </div>
        {f && (
          <div className="focus-tags">
            {[f.work, f.seniority, f.contract, f.salary].filter(Boolean).map((x) => (
              <span key={x}>{x}</span>
            ))}
          </div>
        )}
        <p className="job-summary">{top.match?.summary || top.description_preview || "Open the posting to compare it with your verified experience."}</p>
        {!!top.match?.strengths?.length && (
          <ul className="swipe-strengths">
            {top.match.strengths.slice(0, 2).map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        )}
      </article>
      <div className="swipe-actions">
        <button className="button secondary" aria-label="Skip" onClick={() => commit("skipped")}>
          <X size={18} /> Skip
        </button>
        <button className="text-button" onClick={() => open(top.id)}>
          Details <ArrowUpRight size={16} />
        </button>
        <button className="button primary" aria-label="Shortlist" onClick={() => commit("saved")}>
          <Bookmark size={18} /> Shortlist
        </button>
      </div>
      {undoButton}
    </div>
  );
}
