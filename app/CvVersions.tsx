"use client";
import { useEffect, useState } from "react";
import { LoaderCircle, Plus, Sparkles, Trash2 } from "lucide-react";

export type CvVersion = { id: string; name: string; headline: string; keywords: string[]; fact_ids: string[] };
type Fact = { id: string; category: string; text: string; verified: boolean };

const newId = () => "v" + Math.random().toString(36).slice(2, 10);

// Target roles over the verified evidence: each keeps a headline, the keywords that
// find such roles, and the facts its CV leads with (backend/career/cv_versions.py).
export default function CvVersions({
  versions,
  facts,
  aiReady,
  save,
  suggest,
}: {
  versions: CvVersion[];
  facts: Fact[];
  aiReady: boolean;
  save: (items: CvVersion[]) => Promise<void>;
  suggest: () => Promise<Omit<CvVersion, "id">[]>;
}) {
  const verified = facts.filter((f) => f.verified && f.category.toLowerCase() !== "contact");
  const [draft, setDraft] = useState<CvVersion[]>(versions);
  const [keywordText, setKeywordText] = useState<Record<string, string>>({});
  const [suggested, setSuggested] = useState<Omit<CvVersion, "id">[]>([]);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => setDraft(versions), [versions]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(versions);
  const edit = (id: string, change: Partial<CvVersion>) => setDraft(draft.map((v) => (v.id === id ? { ...v, ...change } : v)));
  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    try {
      await fn();
    } finally {
      setBusy("");
    }
  };
  const add = (v: Omit<CvVersion, "id">) => {
    const id = newId();
    setDraft([...draft, { ...v, id }]);
    setOpen(id);
  };

  return (
    <section className="panel">
      <h2>CV versions</h2>
      <p className="field-help">
        One version per kind of role you apply for, up to five. Each has its own CV headline, the keywords that find such roles (added to your search), and the facts its
        CV leads with. Every job is matched to the version that fits it best, and an application is written for that role. Your verified evidence stays the same for all.
      </p>
      <div className="button-row">
        <button
          className="button secondary"
          disabled={!!busy || !aiReady || !verified.length}
          onClick={() => run("suggest", async () => setSuggested(await suggest()))}
        >
          {busy === "suggest" ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}
          Suggest target roles from my CV
        </button>
        <button className="text-button" disabled={draft.length >= 5 || !verified.length} onClick={() => add({ name: "", headline: "", keywords: [], fact_ids: [] })}>
          <Plus size={15} /> Add a version
        </button>
      </div>
      {!verified.length && <p className="muted-text">Verify some evidence above first.</p>}
      {suggested.length > 0 && (
        <div className="cv-suggestions">
          {suggested.map((r, i) => (
            <div className="cv-suggestion" key={i}>
              <div>
                <strong>{r.name}</strong>
                <p className="muted-text">
                  {r.headline} · {r.keywords.join(", ")} · leads with {r.fact_ids.length} fact{r.fact_ids.length === 1 ? "" : "s"}
                </p>
              </div>
              <button
                className="text-button"
                disabled={draft.length >= 5}
                onClick={() => {
                  add(r);
                  setSuggested(suggested.filter((_, n) => n !== i));
                }}
              >
                Add
              </button>
            </div>
          ))}
        </div>
      )}
      {draft.map((v) => (
        <div className="cv-version" key={v.id}>
          <div className="cv-version-head">
            <button className="cv-version-name" onClick={() => setOpen(open === v.id ? null : v.id)} aria-expanded={open === v.id}>
              <strong>{v.name || "Untitled version"}</strong>
              <span className="muted-text">
                {v.keywords.length} keyword{v.keywords.length === 1 ? "" : "s"} · {v.fact_ids.length} lead fact{v.fact_ids.length === 1 ? "" : "s"}
              </span>
            </button>
            <button className="text-button" aria-label={"Remove " + (v.name || "version")} onClick={() => setDraft(draft.filter((x) => x.id !== v.id))}>
              <Trash2 size={15} />
            </button>
          </div>
          {open === v.id && (
            <div className="cv-version-body">
              <label>
                Target role
                <input value={v.name} maxLength={80} placeholder="Hydrologist" onChange={(e) => edit(v.id, { name: e.target.value })} />
              </label>
              <label>
                CV headline
                <input value={v.headline} maxLength={200} placeholder="Hydrologist building flood early-warning models" onChange={(e) => edit(v.id, { headline: e.target.value })} />
              </label>
              <label>
                Keywords that find these roles (comma separated)
                <input
                  value={keywordText[v.id] ?? v.keywords.join(", ")}
                  onChange={(e) => {
                    setKeywordText({ ...keywordText, [v.id]: e.target.value });
                    edit(v.id, { keywords: e.target.value.split(",").map((k) => k.trim()).filter(Boolean).slice(0, 15) });
                  }}
                />
              </label>
              <fieldset>
                <legend>Facts this CV leads with</legend>
                {verified.map((f) => (
                  <label className="cv-fact" key={f.id}>
                    <input
                      type="checkbox"
                      checked={v.fact_ids.includes(f.id)}
                      onChange={(e) => edit(v.id, { fact_ids: e.target.checked ? [...v.fact_ids, f.id] : v.fact_ids.filter((x) => x !== f.id) })}
                    />
                    <span>
                      <small>{f.category}</small> {f.text}
                    </span>
                  </label>
                ))}
              </fieldset>
            </div>
          )}
        </div>
      ))}
      {(dirty || draft.length > 0) && (
        <div className="button-row">
          <button
            className="button primary"
            disabled={!!busy || !dirty || draft.some((v) => v.name.trim().length < 2)}
            onClick={() => run("save", async () => save(draft.map((v) => ({ ...v, name: v.name.trim(), headline: v.headline.trim() }))))}
          >
            {busy === "save" && <LoaderCircle className="spin" size={17} />}
            Save CV versions
          </button>
          {dirty && <span className="danger-text">Unsaved changes</span>}
        </div>
      )}
    </section>
  );
}
