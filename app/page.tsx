"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  BriefcaseBusiness,
  Search,
  FileText,
  ShieldCheck,
  Radio,
  SlidersHorizontal,
  Link2,
  Plus,
  RefreshCw,
  Check,
  ChevronRight,
  ArrowUpRight,
  Bookmark,
  Upload,
  Download,
  X,
  LoaderCircle,
  Inbox,
  Send,
  FlaskConical,
  UserRound,
  Users,
  LogOut,
  KeyRound,
  Mail,
  MessageCircleQuestion,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { toast, Toaster } from "sonner";
type Fact = {
  id: string;
  category: string;
  text: string;
  source_quote: string;
  verified: boolean;
};
type Profile = { name: string; headline: string; facts: Fact[] };
type Match = {
  score: number;
  summary: string;
  mode: string;
  strengths: string[];
  gaps: string[];
  requirements: {
    requirement: string;
    mandatory: boolean;
    status: string;
    reason: string;
    evidence_ids: string[];
  }[];
};
type Job = {
  id: string;
  title: string;
  company: string;
  location: string;
  description_preview?: string;
  description?: string;
  url: string;
  source: string;
  deadline: string | null;
  posted?: string | null;
  created?: string;
  expired: boolean;
  status: string;
  match: null | Match;
  match_attempts?: number;
};
type Para = { text: string; evidence_ids: string[] };
type Doc = { title: string; paragraphs: Para[] };
type Pack = {
  cv: Doc;
  cover_letter: Doc;
  answers: {
    question: string;
    answer: string;
    evidence_ids: string[];
    character_limit: number | null;
  }[];
  additional_documents: Doc[];
  checklist: string[];
  missing_information: string[];
};
type App = {
  id: string;
  job_id: string;
  title: string;
  company: string;
  status: string;
  error?: string;
  package?: Pack;
  review_notes?: string[];
};
type Prefs = {
  keywords: string[];
  locations: string[];
  contract_types: string[];
  excluded_keywords: string[];
  min_score: number;
  notify_channels: string[];
  alerts_enabled: boolean;
  max_alerts_per_run: number;
  alert_mode: string;
  email_digest: boolean;
  location_mode: string;
  scan_interval_hours: number;
};
type Run = {
  id: string;
  status: string;
  created: string;
  completed?: string;
  trigger?: string;
  added?: number;
  matched?: number;
  alerts?: number;
  archived?: number;
  delivered?: Record<string, string>;
  error?: string;
  progress?: string;
  sources?: {
    name: string;
    status: string;
    error?: string;
    received?: number;
    relevant?: number;
    added?: number;
    pages?: number;
  }[];
  warnings?: string[];
};
type Alert = { id: string; job_id: string; channel: string; status: string; created: string };
type Source = { id: string; kind: string; value: string; enabled: boolean };
type Suggested = { kind: string; value: string; label: string; note: string };
type Account = {
  id: string;
  email: string;
  name: string;
  role: string;
  plan: string;
  has_openai_key: boolean;
  has_imap: boolean;
  sponsored?: boolean;
  organisation?: string;
  last_active?: string;
  created?: string;
};
type Plan = {
  id: string;
  label: string;
  sources: number;
  evaluations_per_run: number;
  packages_per_month: number;
  evaluations_per_month?: number | null;
  schedule: boolean;
  packages_used: number;
  evaluations_used?: number;
};
type State = {
  user: Account;
  plan: Plan;
  app_name: string;
  profile: Profile;
  preferences: Prefs;
  connections: Record<string, boolean>;
  jobs: Job[];
  applications: App[];
  sources: Source[];
  runs: Run[];
  schedule: { enabled: boolean };
  scheduler: { mode: string; threads: Record<string, boolean> };
  alerts: Alert[];
  inbox_unread: number;
  telegram: { bot_configured: boolean; linked: boolean; username: string; via_env: boolean };
  source_kinds: Record<string, string>;
  suggested_sources: Suggested[];
};
type Metrics = Account & {
  evaluations_this_month?: number;
  verified_facts: number;
  sources: number;
  searches: number;
  jobs: number;
  evaluated: number;
  packages: number;
  packages_requested: number;
  telegram_linked: boolean;
  activated: boolean;
  drafted: boolean;
};
type Overview = {
  users: Metrics[];
  invites: { code: string; note: string; created: string; used_by: string | null }[];
  waitlist: { email: string; name: string; note: string; created: string; invited?: string | null; code?: string }[];
  totals: { users: number; activated: number; drafted: number; with_key: number; telegram: number; sponsored?: number; sponsored_seats?: number; sponsored_evaluations_this_month?: number; server_key_calls_this_month?: number; server_key_monthly_cap?: number };
  plans: Record<string, { label: string }>;
};
const defaults: Prefs = {
  keywords: [
    "data science",
    "machine learning",
    "climate",
    "geospatial",
    "hydrology",
    "remote sensing",
    "digital agriculture",
  ],
  locations: ["Ethiopia", "Remote", "Africa"],
  contract_types: ["Consultancy", "Full-time"],
  excluded_keywords: [],
  min_score: 70,
  notify_channels: [],
  alerts_enabled: false,
  max_alerts_per_run: 10,
  alert_mode: "each",
  email_digest: true,
  location_mode: "soft",
  scan_interval_hours: 6,
};
const emptyAccount: Account = { id: "", email: "", name: "", role: "member", plan: "beta", has_openai_key: false, has_imap: false, sponsored: false };
const initial: State = {
  user: emptyAccount,
  plan: { id: "beta", label: "Beta", sources: 20, evaluations_per_run: 50, packages_per_month: 30, schedule: true, packages_used: 0 },
  app_name: "Jobs Find AI",
  profile: { name: "", headline: "", facts: [] },
  preferences: defaults,
  connections: {},
  jobs: [],
  applications: [],
  sources: [],
  runs: [],
  schedule: { enabled: false },
  scheduler: { mode: "off", threads: {} },
  alerts: [],
  inbox_unread: 0,
  telegram: { bot_configured: false, linked: false, username: "", via_env: false },
  source_kinds: {},
  suggested_sources: [],
};
const nav = [
  ["opportunities", "Opportunities", Search],
  ["applications", "Applications", FileText],
  ["profile", "My evidence", ShieldCheck],
  ["sources", "Job sources", Radio],
  ["settings", "Preferences", SlidersHorizontal],
  ["account", "Account", UserRound],
] as const;
const titles: Record<string, string> = {
  opportunities: "Find the work that fits.",
  applications: "Make every application count.",
  profile: "Your experience. Your evidence.",
  sources: "Keep the right opportunities in view.",
  settings: "Define your next opportunity.",
  account: "Your account and connections.",
  admin: "Beta cohort.",
};
const intros: Record<string, string> = {
  opportunities: "A considered shortlist, grounded in what you actually do.",
  applications: "Prepare, review, and export. You decide what gets submitted.",
  profile:
    "Review your CV facts before they guide recommendations or applications.",
  sources: "Choose employer feeds, job boards and email alerts for your search.",
  settings:
    "Tell the assistant what matters, and how you want to hear about it.",
  account: "Your AI key, mailbox and Telegram stay private to your workspace.",
  admin: "Who has activated, who is drafting, and invitations.",
};
const sourceHelp: Record<string, { label: string; placeholder: string; help: string }> = {
  reliefweb: {
    label: "Search query",
    placeholder: 'climate OR GIS OR "data science"',
    help: "Development-sector jobs from ReliefWeb.",
  },
  imap: {
    label: "Label or folder (optional)",
    placeholder: "JobsFindAI",
    help: "Reads job-alert emails (LinkedIn, Devex, UNjobs, Impactpool…) from a label in your own mailbox. Connect the mailbox under Account first. Needs your AI key.",
  },
  gmail: {
    label: "Gmail search (optional)",
    placeholder: "label:JobsFindAI newer_than:7d",
    help: "Owner account only: Gmail OAuth import configured on the server.",
  },
  rss: {
    label: "Feed address",
    placeholder: "https://example.org/jobs/feed.xml",
    help: "Any RSS or Atom feed of postings. Short entries are completed from the linked page.",
  },
  page: {
    label: "Careers page address",
    placeholder: "https://example.org/careers",
    help: "A public vacancies page. AI identifies the postings on it and each new posting page is read once. Needs your AI key.",
  },
  greenhouse: { label: "Board identifier", placeholder: "e.g. acme", help: "The slug from boards.greenhouse.io/<slug>." },
  lever: { label: "Board identifier", placeholder: "e.g. acme", help: "The slug from jobs.lever.co/<slug>." },
  workable: { label: "Board identifier", placeholder: "e.g. cgiar", help: "The slug from apply.workable.com/<slug>." },
  smartrecruiters: { label: "Company identifier", placeholder: "e.g. AcmeCorp", help: "The company name in jobs.smartrecruiters.com/<Company>." },
  ashby: { label: "Board identifier", placeholder: "e.g. acme", help: "The slug from jobs.ashbyhq.com/<slug>." },
  remotive: { label: "Categories", placeholder: "data,artificial-intelligence,research", help: "Remote roles by category. Check each posting's eligible regions." },
};
const date = (v: string | null | undefined, empty = "Deadline not listed") =>
  v
    ? new Date(v).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : empty;
const link = (v: string) => (/^https?:\/\//i.test(v) ? v : undefined);
const PAGE = 30;
const HEADERS = { "X-Requested-With": "CareerPilot" };
type Analytics = { provider: string; key: string; host: string; replay: boolean } | null;
type PostHog = {
  init: (key: string, options: Record<string, unknown>) => void;
  capture: (event: string, props?: Record<string, unknown>) => void;
  identify: (id: string, props?: Record<string, unknown>) => void;
  reset: () => void;
  captureException?: (error: unknown, props?: Record<string, unknown>) => void;
  __SV?: number;
};
const ph = (): PostHog | undefined => (window as unknown as { posthog?: PostHog }).posthog;
// Session replay with every input masked and all personal text hidden; people
// are identified by their anonymous account ID, never by email.
// This mirrors PostHog's official snippet: a queue object on window.posthog that
// array.js consumes on load (init calls in `_i`, method calls on the instance array).
const POSTHOG_METHODS =
  "init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSurveysLoaded onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug getPageViewId captureTraceFeedback captureTraceMetric".split(
    " ",
  );
function installPosthogSnippet(host: string) {
  const w = window as unknown as { posthog?: unknown };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const e: any = (w.posthog as any) || [];
  if (e.__SV) return;
  w.posthog = e;
  e._i = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  e.init = function (token: string, config: any, name?: string) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g = (t: any, m: string) => {
      const parts = m.split(".");
      if (parts.length === 2) {
        t = t[parts[0]];
        m = parts[1];
      }
      t[m] = function () {
        // eslint-disable-next-line prefer-rest-params
        t.push([m].concat(Array.prototype.slice.call(arguments, 0)));
      };
    };
    const script = document.createElement("script");
    script.type = "text/javascript";
    script.crossOrigin = "anonymous";
    script.async = true;
    script.src = host.replace(/\/$/, "").replace(".i.posthog.com", "-assets.i.posthog.com") + "/static/array.js";
    const first = document.getElementsByTagName("script")[0];
    (first?.parentNode ?? document.head).insertBefore(script, first ?? null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let u: any = e;
    if (name !== undefined) u = e[name] = [];
    else name = "posthog";
    u.people = u.people || [];
    u.toString = (stub?: boolean) => "posthog" + (name !== "posthog" ? "." + name : "") + (stub ? "" : " (stub)");
    u.people.toString = () => u.toString(1) + ".people (stub)";
    POSTHOG_METHODS.forEach((m) => g(u, m));
    e._i.push([token, config, name]);
  };
  e.__SV = 1;
}
function startAnalytics(config: Analytics) {
  if (!config || config.provider !== "posthog" || !config.key) return;
  installPosthogSnippet(config.host);
  ph()?.init(config.key, {
    api_host: config.host,
    person_profiles: "identified_only",
    capture_pageview: true,
    capture_pageleave: true,
    autocapture: true,
    capture_dead_clicks: true,
    capture_exceptions: true,
    capture_performance: { web_vitals: true },
    capture_heatmaps: true,
    respect_dnt: true,
    disable_session_recording: !config.replay,
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "[data-ph-mask], .fact, .posting-text, .assistant-msg, .package-dialog textarea, .package-dialog h3, .job-title, .company-name, .avatar, .admin-table td, details p",
      blockSelector: "[data-ph-block]",
    },
  });
}
const track = (event: string, props?: Record<string, unknown>) => {
  try {
    ph()?.capture(event, props);
  } catch {}
};
/** Feature flags from PostHog. Flags default to `fallback` until they have loaded, so
 * the app never blocks on analytics; a flag that is off hides the feature everywhere. */
function useFlags() {
  const [flags, setFlags] = useState<Record<string, string | boolean>>({});
  useEffect(() => {
    let cancelled = false;
    const read = () => {
      const p = ph();
      if (!p?.isFeatureEnabled || cancelled) return;
      const next: Record<string, string | boolean> = {};
      for (const key of FLAGS) {
        try {
          const v = p.getFeatureFlag?.(key);
          if (v !== undefined) next[key] = v as string | boolean;
        } catch {}
      }
      setFlags(next);
    };
    const t = setInterval(() => {
      const p = ph();
      if (p?.onFeatureFlags) {
        clearInterval(t);
        p.onFeatureFlags(read);
        read();
      }
    }, 500);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);
  return (key: (typeof FLAGS)[number], fallback = true) => (key in flags ? flags[key] !== false && flags[key] !== "control" : fallback);
}
const FLAGS = ["assistant-widget", "sponsored-seats-banner"] as const;
const trackError = (error: unknown, props?: Record<string, unknown>) => {
  try {
    ph()?.captureException?.(error, props);
  } catch {}
};
async function call<T = Record<string, unknown>>(path: string, method = "GET", body?: unknown): Promise<T> {
  const form = body instanceof FormData;
  const r = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: {
      ...HEADERS,
      ...(!form && body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? (form ? body : JSON.stringify(body)) : undefined,
  });
  if (!r.ok) {
    let m = "The service could not be reached.";
    try {
      const e = (await r.json()) as { detail?: string };
      if (typeof e.detail === "string") m = e.detail;
    } catch {}
    const err = new Error(m) as Error & { status?: number };
    err.status = r.status;
    if (r.status !== 401) {
      track("api_error", { path: path.replace(/\/[0-9a-f]{32}/g, "/:id"), method, status: r.status, message: m });
      if (r.status >= 500) trackError(err, { path: path.replace(/\/[0-9a-f]{32}/g, "/:id"), status: r.status });
    }
    throw err;
  }
  return r.json() as Promise<T>;
}
function AuthScreen({ setup, onDone }: { setup: { app_name: string; needs_first_account: boolean; invite_only: boolean; owner_email_fixed?: boolean }; onDone: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">(setup.needs_first_account ? "signup" : "login");
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState(""),
    [invite, setInvite] = useState(new URLSearchParams(window.location.search).get("invite") ?? ""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    track(mode === "signup" ? "signup_started" : "login_started", { first_account: setup.needs_first_account });
  }, [mode, setup.needs_first_account]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await call("/auth/" + mode, "POST", { email, password, name, invite });
      track(mode === "signup" ? "signup_completed" : "login_completed", { with_invite: !!invite && !setup.needs_first_account });
      onDone();
    } catch (err) {
      track(mode === "signup" ? "signup_failed" : "login_failed", { message: err instanceof Error ? err.message : "" });
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="workspace">
      <header className="masthead">
        <span className="brand">
          <span className="brandmark">
            <BriefcaseBusiness size={22} />
          </span>
          <span>
            {setup.app_name}
            <small>YOUR NEXT CHAPTER</small>
          </span>
        </span>
      </header>
      <main className="main-content">
        <div className="two-columns">
          <section className="panel">
            <h2>{mode === "login" ? "Sign in" : setup.needs_first_account ? "Create the owner account" : "Create your account"}</h2>
            <form onSubmit={submit}>
              {mode === "signup" && (
                <label className="field">
                  Name
                  <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
                </label>
              )}
              <label className="field">
                Email
                <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
              </label>
              <label className="field">
                Password
                <input type="password" required minLength={mode === "signup" ? 10 : 1} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "signup" ? "new-password" : "current-password"} />
                {mode === "signup" && <span className="field-help">At least 10 characters.</span>}
              </label>
              {mode === "signup" && !setup.needs_first_account && setup.invite_only && (
                <label className="field">
                  Invite code
                  <input required value={invite} onChange={(e) => setInvite(e.target.value)} />
                  <span className="field-help">The beta is invitation-only. Use the code you received.</span>
                </label>
              )}
              {mode === "signup" && setup.needs_first_account && (
                <label className="field">
                  Setup code
                  <input required type="password" autoComplete="off" value={invite} onChange={(e) => setInvite(e.target.value)} />
                  <span className="field-help">The APP_TOKEN from the server's environment. It proves you deployed this instance.</span>
                </label>
              )}
              {error && <p className="connection-error">{error}</p>}
              <button className="button primary" disabled={busy}>
                {busy ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />}
                {mode === "login" ? "Sign in" : "Create account"}
              </button>
            </form>
            {!setup.needs_first_account && (
              <p className="field-help">
                {mode === "login" ? "Have an invite? " : "Already have an account? "}
                <button className="text-button" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
                  {mode === "login" ? "Create an account" : "Sign in"}
                </button>
              </p>
            )}
          </section>
          <section className="panel">
            <h2>What this is</h2>
            <p>A personal job-search assistant. It collects postings from sources you choose, explains how each one matches the CV facts you verified, alerts you, and drafts applications only when you ask.</p>
            <p>{(setup as { sponsored_seats_left?: number }).sponsored_seats_left ? "Early members get AI usage included; later members bring their own OpenAI key." : "You bring your own OpenAI key."} Nothing is ever submitted to employers on your behalf.</p>
            <p className="field-help">
              <a href="/">About Jobs Find AI</a> · <a href="/privacy.html" target="_blank" rel="noreferrer">Privacy</a> · <a href="/terms.html" target="_blank" rel="noreferrer">Terms</a>
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}
function Assistant() {
  const [open, setOpen] = useState(false),
    [input, setInput] = useState(""),
    [busy, setBusy] = useState(false),
    [messages, setMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([]),
    [suggestions, setSuggestions] = useState<string[]>([]);
  useEffect(() => {
    if (open && !suggestions.length) call<{ questions: string[] }>("/assistant/suggestions").then((r) => setSuggestions(r.questions)).catch(() => {});
  }, [open, suggestions.length]);
  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const next = [...messages, { role: "user" as const, content: q }];
    setMessages(next);
    setInput("");
    setBusy(true);
    track("assistant_question_asked", { turns: next.length, suggested: suggestions.includes(q) });
    try {
      const r = await call<{ reply: string }>("/assistant/chat", "POST", { messages: next.slice(-16) });
      setMessages([...next, { role: "assistant", content: r.reply }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: e instanceof Error ? e.message : "Something went wrong." }]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="assistant">
      {open && (
        <div className="assistant-panel" role="dialog" aria-label="Help assistant">
          <div className="assistant-head">
            <strong>Help assistant</strong>
            <button className="icon-button" aria-label="Close" onClick={() => setOpen(false)}>
              <X size={16} />
            </button>
          </div>
          <div className="assistant-body">
            {messages.length === 0 && (
              <>
                <p className="muted-text">Ask how anything works: sources, matching, alerts, applications, your plan.</p>
                <div className="assistant-chips">
                  {suggestions.map((q) => (
                    <button key={q} onClick={() => send(q)}>
                      {q}
                    </button>
                  ))}
                </div>
              </>
            )}
            {messages.map((m, i) => (
              <div key={i} className={"assistant-msg " + m.role}>
                {m.content}
              </div>
            ))}
            {busy && <div className="assistant-msg assistant muted-text">Thinking…</div>}
          </div>
          <form
            className="assistant-input"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question…" maxLength={600} />
            <button className="button primary" disabled={busy || !input.trim()}>
              <Send size={15} />
            </button>
          </form>
        </div>
      )}
      <button className="assistant-toggle" aria-label="Help" onClick={() => setOpen(!open)}>
        {open ? <X size={18} /> : <MessageCircleQuestion size={20} />}
        <span>Help</span>
      </button>
    </div>
  );
}
export default function Home() {
  const [setup, setSetup] = useState<null | { app_name: string; needs_first_account: boolean; invite_only: boolean; owner_email_fixed?: boolean }>(null);
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [s, setS] = useState<State>(initial),
    [tab, setTab] = useState("opportunities"),
    [busy, setBusy] = useState("");
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [sort, setSort] = useState("score"),
    [hideExpired, setHideExpired] = useState(true),
    [limit, setLimit] = useState(PAGE),
    [selected, setSelected] = useState<string | null>(null),
    [detail, setDetail] = useState<Job | null>(null),
    [addOpen, setAddOpen] = useState(false),
    [cvText, setCvText] = useState(""),
    [profile, setProfile] = useState<Profile>(initial.profile),
    [prefs, setPrefs] = useState(defaults),
    [sourceKind, setSourceKind] = useState("reliefweb"),
    [sourceValue, setSourceValue] = useState(""),
    [sourceTest, setSourceTest] = useState<null | { received: number; sample: { title: string; company: string; location: string; url: string }[] }>(null),
    [editing, setEditing] = useState<App | null>(null),
    [draft, setDraft] = useState<Pack | null>(null),
    [linkCode, setLinkCode] = useState<null | { code: string; bot_username: string }>(null),
    [apiKey, setApiKey] = useState(""),
    [imap, setImap] = useState({ host: "imap.gmail.com", port: 993, username: "", password: "", folder: "JobsFindAI" }),
    [pw, setPw] = useState({ current: "", new: "" }),
    [accountName, setAccountName] = useState(""),
    [overview, setOverview] = useState<Overview | null>(null),
    [inviteCount, setInviteCount] = useState(5),
    [inviteNote, setInviteNote] = useState(""),
    [newCodes, setNewCodes] = useState<string[]>([]);
  const refresh = useCallback(async () => {
    const data = await call<State>("/state");
    setS(data);
    setSignedIn(true);
    return data as State;
  }, []);
  const boot = useCallback(async () => {
    try {
      const s = await call<{ app_name: string; needs_first_account: boolean; invite_only: boolean; owner_email_fixed?: boolean; analytics?: Analytics }>("/setup");
      setSetup(s);
      startAnalytics(s.analytics ?? null);
    } catch {}
    try {
      const d = await refresh();
      setProfile(d.profile);
      setPrefs({ ...defaults, ...d.preferences });
      setAccountName(d.user.name);
      try {
        ph()?.identify(d.user.id, { plan: d.user.plan, role: d.user.role, has_key: d.connections.ai, sponsored: !!d.user.sponsored, organisation: d.user.organisation || "", sources: d.sources.length, verified_facts: d.profile.facts.filter((f) => f.verified).length });
        // Group analytics: members of the same institution or cohort are analysed together.
        if (d.user.organisation) ph()?.group?.("organisation", d.user.organisation.toLowerCase().replace(/[^a-z0-9]+/g, "-"), { name: d.user.organisation });
      } catch {}
    } catch (e) {
      setSignedIn(false);
    }
  }, [refresh]);
  useEffect(() => {
    boot();
  }, [boot]);
  useEffect(() => {
    if (!signedIn) return;
    const t = setInterval(() => refresh().catch((e: Error & { status?: number }) => e.status === 401 && setSignedIn(false)), 8000);
    return () => clearInterval(t);
  }, [signedIn, refresh]);
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("job");
    if (id) setSelected(id);
  }, []);
  // Web analytics: each dashboard tab counts as a page so paths show up in PostHog's web analytics view.
  const firstTab = useRef(true);
  useEffect(() => {
    if (firstTab.current) {
      firstTab.current = false;
      return;
    }
    if (signedIn) track("$pageview", { $current_url: window.location.origin + "/app/" + tab, tab });
  }, [tab, signedIn]);
  const flag = useFlags();
  const [seenRun, setSeenRun] = useState<{ id: string; status: string } | null>(null);
  useEffect(() => {
    const r = s.runs[0];
    if (!r) return;
    if (seenRun && seenRun.id === r.id && seenRun.status === r.status) return;
    if (seenRun && seenRun.id === r.id && ["queued", "running"].includes(seenRun.status) && !["queued", "running"].includes(r.status)) {
      const seconds = r.completed ? Math.round((new Date(r.completed).getTime() - new Date(r.created).getTime()) / 1000) : undefined;
      if (r.status === "completed") {
        track("job_search_completed", { seconds, added: r.added ?? 0, matched: r.matched ?? 0, alerts: r.alerts ?? 0, failed_sources: (r.sources ?? []).filter((x) => x.status === "failed").length, warnings: (r.warnings ?? []).length, trigger: r.trigger });
      } else {
        track("job_search_failed", { seconds, status: r.status, error: r.error, trigger: r.trigger });
      }
    }
    setSeenRun({ id: r.id, status: r.status });
  }, [s.runs, seenRun]);
  useEffect(() => {
    if (!selected || !signedIn) {
      setDetail(null);
      return;
    }
    let live = true;
    const opened = s.jobs.find((j) => j.id === selected);
    track("job_result_opened", { score: opened?.match?.score ?? null, source: opened?.source, unread: unreadIds.has(selected) });
    call<Job>(`/jobs/${selected}`)
      .then((d) => {
        if (live) setDetail(d);
      })
      .catch(() => {});
    const unread = s.alerts.some(
      (a) => a.job_id === selected && a.channel === "inapp" && a.status === "unread",
    );
    if (unread) call("/inbox/read", "POST", { job_ids: [selected] }).then(() => refresh()).catch(() => {});
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, signedIn]);
  useEffect(() => {
    if (tab === "admin" && s.user.role === "admin") {
      call<Overview>("/admin/overview").then(setOverview).catch(() => {});
    }
  }, [tab, s.user.role]);
  const act = async (
    name: string,
    fn: () => Promise<unknown>,
    message?: string,
  ) => {
    setBusy(name);
    try {
      await fn();
      await refresh();
      if (selected) {
        try {
          setDetail(await call<Job>(`/jobs/${selected}`));
        } catch {}
      }
      if (message) toast.success(message);
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 401) setSignedIn(false);
      toast.error(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy("");
    }
  };
  const evidenceDirty = JSON.stringify(profile) !== JSON.stringify(s.profile) && s.profile.facts.length > 0;
  useEffect(() => {
    if (!evidenceDirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [evidenceDirty]);
  const lastCompleted = s.runs.find((r) => r.status === "completed");
  const nextRun =
    s.schedule.enabled && lastCompleted
      ? new Date(new Date(lastCompleted.created).getTime() + (s.preferences.scan_interval_hours || 6) * 3600000)
      : null;
  const verified = s.profile.facts.filter((f) => f.verified).length,
    active = s.runs.some(
      (r) =>
        ["queued", "running"].includes(r.status) &&
        Date.now() - new Date(r.created).getTime() < 1800000,
    );
  const unreadIds = new Set(
    s.alerts.filter((a) => a.channel === "inapp" && a.status === "unread").map((a) => a.job_id),
  );
  const visible = s.jobs
    .filter((j) => {
      if (filter === "inbox") return unreadIds.has(j.id);
      if (filter === "strong") return (j.match?.score ?? 0) >= prefs.min_score && j.status !== "skipped" && j.status !== "archived";
      if (filter === "saved") return j.status === "saved" || j.status === "applied";
      if (filter === "skipped") return j.status === "skipped" || j.status === "archived";
      return j.status !== "skipped" && j.status !== "archived";
    })
    .filter((j) => !hideExpired || !j.expired || filter === "saved")
    .filter((j) =>
      `${j.title} ${j.company} ${j.location} ${j.source}`.toLowerCase().includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "newest"
        ? (b.posted || b.created || "").localeCompare(a.posted || a.created || "")
        : (b.match?.score ?? -1) - (a.match?.score ?? -1) ||
          (b.posted || b.created || "").localeCompare(a.posted || a.created || ""),
    );
  const jobs = visible.slice(0, limit);
  const job = detail && detail.id === selected ? detail : s.jobs.find((j) => j.id === selected) ?? null;
  const decide = (j: Job, status: string) =>
    act(
      "decision",
      async () => {
        track(status === "saved" ? "job_saved" : status === "skipped" ? "job_skipped" : status === "applied" ? "job_marked_applied" : "job_status_changed", { score: j.match?.score ?? null, source: j.source });
        await call(`/jobs/${j.id}/decision`, "PUT", { status });
      },
      "Job updated",
    );
  const prepare = (j: Job) =>
    act(
      "prepare",
      async () => {
        track("application_created", { score: j.match?.score ?? null, source: j.source, packages_used: s.plan.packages_used });
        await call(`/jobs/${j.id}/prepare`, "POST");
        setSelected(null);
        setTab("applications");
      },
      "Application preparation requested",
    );
  const upload = async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    await act(
      "upload",
      async () => {
        const started = Date.now();
        const p = await call<Profile>("/profile/upload", "POST", body);
        setProfile(p);
        track("cv_uploaded", { method: "file", facts: p.facts.length, seconds: Math.round((Date.now() - started) / 1000), size_kb: Math.round(file.size / 1024) });
      },
      "Imported. Review and verify your evidence.",
    );
  };
  const download = async (a: App) => {
    try {
      const r = await fetch(`/api/applications/${a.id}/download`, { credentials: "same-origin", headers: HEADERS });
      if (!r.ok) throw new Error("Documents are not ready to download.");
      track("application_exported", {});
      const url = URL.createObjectURL(await r.blob()),
        el = document.createElement("a");
      el.href = url;
      el.download = "application_package.zip";
      el.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      toast.error(String(e));
    }
  };
  const savePrefs = () =>
    act(
      "preferences",
      () =>
        call("/preferences", "PUT", {
          ...prefs,
          keywords: prefs.keywords.filter(Boolean),
          locations: prefs.locations.filter(Boolean),
          contract_types: prefs.contract_types.filter(Boolean),
          excluded_keywords: prefs.excluded_keywords.filter(Boolean),
        }),
      "Preferences saved",
    );
  const addSource = (kind: string, value: string) =>
    act(
      "source",
      async () => {
        track("job_source_selected", { kind, suggested: s.suggested_sources.some((x) => x.kind === kind && x.value === value) });
        await call("/sources", "POST", { kind, value, enabled: true });
        setSourceValue("");
        setSourceTest(null);
      },
      "Source added",
    );
  const testSource = () =>
    act("test-source", async () => {
      track("job_source_tested", { kind: sourceKind });
      setSourceTest(null);
      setSourceTest(
        await call<{ received: number; sample: { title: string; company: string; location: string; url: string }[] }>("/sources/test", "POST", { kind: sourceKind, value: sourceValue, enabled: true }),
      );
    });
  const signOut = () =>
    act("logout", async () => {
      await call("/auth/logout", "POST");
      track("logout", {});
      try {
        ph()?.reset();
      } catch {}
      setSignedIn(false);
      setS(initial);
      window.location.href = "/";
    });
  const lastRun = s.runs[0];
  if (signedIn === false) {
    return (
      <>
        <Toaster richColors position="bottom-right" />
        <AuthScreen setup={setup ?? { app_name: "Jobs Find AI", needs_first_account: false, invite_only: true }} onDone={boot} />
      </>
    );
  }
  if (signedIn === null) {
    return (
      <div className="workspace">
        <main className="main-content">
          <p className="muted-text">Loading…</p>
        </main>
      </div>
    );
  }
  const isAdmin = s.user.role === "admin";
  const tabs = isAdmin ? [...nav, ["admin", "Cohort", Users] as const] : nav;
  return (
    <div className="workspace">
      <Toaster richColors position="bottom-right" />
      <header className="masthead">
        <a href="/" className="brand">
          <span className="brandmark">
            <BriefcaseBusiness size={22} />
          </span>
          <span>
            {s.app_name}
            <small>YOUR NEXT CHAPTER</small>
          </span>
        </a>
        <div className="header-right">
          {s.inbox_unread > 0 && (
            <button
              className="button secondary"
              onClick={() => {
                setTab("opportunities");
                setFilter("inbox");
              }}
            >
              <Inbox size={16} /> {s.inbox_unread} new match{s.inbox_unread === 1 ? "" : "es"}
            </button>
          )}
          <span className={"connection-pill " + (s.connections.ai ? "ready" : "")}>
            <span />
            {s.connections.ai ? "AI ready" : "Add your AI key"}
          </span>
          <button className="icon-button" aria-label="Account" onClick={() => setTab("account")}>
            <UserRound size={19} />
          </button>
          <span className="avatar" title={s.user.email}>
            {(s.user.name || s.profile.name || s.user.email)
              .split(/[\s@]/)
              .filter(Boolean)
              .slice(0, 2)
              .map((n) => n[0].toUpperCase())
              .join("")}
          </span>
        </div>
      </header>
      <Tabs value={tab} onValueChange={setTab} className="main-tabs">
        <div className="nav-bar">
          <TabsList className="nav-tabs" variant="line">
            {tabs.map(([id, label, Icon]) => (
              <TabsTrigger key={id} value={id}>
                <Icon />
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          <span className="private-note">
            <ShieldCheck size={14} />
            Private workspace
          </span>
        </div>
        <main className="main-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                CAREER WORKSPACE <span>/</span>{" "}
                {tabs.find((n) => n[0] === tab)?.[1].toUpperCase()}
              </div>
              <h1>{titles[tab]}</h1>
              <p>{intros[tab]}</p>
            </div>
            {tab === "opportunities" && (
              <div className="heading-actions">
                <button className="button secondary" onClick={() => setAddOpen(true)}>
                  <Plus size={17} />
                  Add a job
                </button>
                <button
                  className="button primary"
                  disabled={!!busy || active}
                  onClick={() =>
                    act(
                      "scan",
                      async () => {
                        track("job_search_started", { sources: s.sources.filter((x) => x.enabled).length, has_key: s.connections.ai, verified_facts: verified });
                        await call("/scan", "POST");
                      },
                      "Search started",
                    )
                  }
                >
                  {active ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}{" "}
                  {active ? "Searching…" : "Run search"}
                </button>
              </div>
            )}
          </div>
          {tab === "opportunities" && (
            <p className={"field-help " + (lastRun?.status === "failed" || lastRun?.sources?.some((x) => x.status === "failed") ? "danger-text" : "")}>
              {active && lastRun?.progress
                ? lastRun.progress
                : lastRun?.status === "failed"
                  ? lastRun.error
                  : lastRun?.sources?.some((x) => x.status === "failed")
                    ? "Last search: " + lastRun.sources.filter((x) => x.status === "failed").map((x) => x.name + " failed").join(", ") + ". See Job sources → Search activity."
                    : lastCompleted
                      ? `Last search ${new Date(lastCompleted.created).toLocaleString()} · ${lastCompleted.added ?? 0} new · ${lastCompleted.matched ?? 0} evaluated` +
                        (nextRun ? ` · next automatic search ${nextRun.toLocaleString()}` : " · scheduled searches off")
                      : "No search yet. Add sources, then run your first search."}
            </p>
          )}
          {(!s.connections.ai || !verified || !s.sources.length) && tab !== "admin" && (
            <div className="onboarding">
              <div className="onboarding-title">
                <span className="step-icon">
                  <ChevronRight size={20} />
                </span>
                <div>
                  <strong>Set up your personal search</strong>
                  <span>Three steps to your first useful shortlist.</span>
                </div>
              </div>
              {[
                [s.connections.ai, s.connections.ai_sponsored ? "AI included in your seat" : "Add your OpenAI key", () => setTab("account")],
                [verified > 0, "Verify your CV", () => setTab("profile")],
                [s.sources.length > 0, "Add job sources", () => setTab("sources")],
              ].map(([done, label, action], i) => (
                <button key={i} className={done ? "done" : ""} onClick={action as () => void}>
                  <span>{done ? <Check size={14} /> : i + 1}</span>
                  {label as string}
                </button>
              ))}
            </div>
          )}
          <TabsContent value="opportunities">
            <div className="stats">
              {[
                [s.jobs.filter((j) => !["skipped", "archived"].includes(j.status)).length, "Opportunities", "In your workspace"],
                [
                  s.jobs.filter((j) => (j.match?.score ?? 0) >= prefs.min_score && !j.expired && !["skipped", "archived"].includes(j.status)).length,
                  "Strong matches",
                  prefs.min_score + "+ relevance score",
                ],
                [s.jobs.filter((j) => j.status === "saved").length, "Shortlisted", "Ready for your next move"],
                [s.applications.length, "Applications", s.applications.filter((a) => a.status === "review").length + " awaiting review"],
              ].map(([n, l, m]) => (
                <div key={String(l)}>
                  <span>{l}</span>
                  <strong>{String(n).padStart(2, "0")}</strong>
                  <small>{m}</small>
                </div>
              ))}
            </div>
            <div className="work-grid">
              <section className="opportunity-list">
                <div className="list-toolbar">
                  <div className="filter-pills">
                    {[
                      ["inbox", `New${s.inbox_unread ? " (" + s.inbox_unread + ")" : ""}`],
                      ["all", "All jobs"],
                      ["strong", "Strong matches"],
                      ["saved", "Shortlist"],
                      ["skipped", "Skipped & archived"],
                    ].map(([v, l]) => (
                      <button
                        key={v}
                        className={filter === v ? "active" : ""}
                        onClick={() => {
                          setFilter(v);
                          setLimit(PAGE);
                        }}
                      >
                        {l}
                      </button>
                    ))}
                  </div>
                  <div className="searchbox">
                    <Search size={17} />
                    <input aria-label="Search opportunities" placeholder="Search jobs, employers, sources" value={query} onChange={(e) => setQuery(e.target.value)} />
                  </div>
                </div>
                <div className="list-toolbar">
                  <label className="channel-row" style={{ gap: 8 }}>
                    <Checkbox checked={hideExpired} onCheckedChange={(v) => setHideExpired(v === true)} />
                    <span className="muted-text">Hide closed deadlines</span>
                  </label>
                  <label className="channel-row" style={{ gap: 8 }}>
                    <span className="muted-text">Sort</span>
                    <Select value={sort} onValueChange={setSort}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="score">Best match</SelectItem>
                        <SelectItem value="newest">Newest</SelectItem>
                      </SelectContent>
                    </Select>
                  </label>
                  {filter === "inbox" && s.inbox_unread > 0 && (
                    <button className="text-button" onClick={() => act("read", () => call("/inbox/read", "POST", { job_ids: [] }), "Inbox cleared")}>
                      Mark all read <Check size={15} />
                    </button>
                  )}
                </div>
                {jobs.length ? (
                  jobs.map((j) => (
                    <article className="job-card" key={j.id}>
                      <div className="job-top">
                        <span className="company-symbol">{j.company.slice(0, 2).toUpperCase() || "JB"}</span>
                        <div className="job-identity">
                          <span className="company-name">
                            {j.company || "Employer not specified"}
                            {unreadIds.has(j.id) && (
                              <span className="tag tag-green" style={{ marginLeft: 8 }}>
                                New
                              </span>
                            )}
                          </span>
                          <button className="job-title" onClick={() => setSelected(j.id)}>
                            {j.title}
                          </button>
                        </div>
                        <span className={"score " + (j.match && j.match.score >= prefs.min_score ? "high" : "")}>
                          {j.match ? (
                            <>
                              <strong>{j.match.score}</strong>
                              <small>{j.match.mode === "keyword" ? "KEYWORD" : "MATCH"}</small>
                            </>
                          ) : (
                            <small>{(j.match_attempts ?? 0) >= 3 ? "PAUSED" : "UNRANKED"}</small>
                          )}
                        </span>
                      </div>
                      <div className="job-meta">
                        <span>{j.location}</span>
                        <span>{j.source}</span>
                        {j.posted && <span>Posted {date(j.posted, "")}</span>}
                        <span className={j.expired ? "danger-text" : ""}>
                          {j.expired ? "Closed · " : ""}
                          {date(j.deadline)}
                        </span>
                      </div>
                      <p className="job-summary">{j.match?.summary || j.description_preview || "Review this posting and compare it with your verified experience."}</p>
                      <div className="job-footer">
                        <span className="tag">
                          {j.status === "saved"
                            ? "Shortlisted"
                            : j.status === "applied"
                              ? "Applied"
                              : j.status === "archived"
                                ? "Archived"
                                : j.status === "skipped"
                                  ? "Skipped"
                                  : j.match?.mode === "keyword"
                                    ? "Eligibility not evaluated"
                                    : j.match
                                      ? "Your review required"
                                      : "Awaiting evaluation"}
                        </span>
                        <div>
                          <button className="icon-button" aria-label="Save job" onClick={() => decide(j, j.status === "saved" ? "new" : "saved")}>
                            <Bookmark size={18} fill={j.status === "saved" ? "currentColor" : "none"} />
                          </button>
                          <button className="text-button" onClick={() => setSelected(j.id)}>
                            Review opportunity <ArrowUpRight size={16} />
                          </button>
                        </div>
                      </div>
                    </article>
                  ))
                ) : (
                  <div className="empty-jobs">
                    <div className="empty-illustration">
                      <Search size={35} />
                      <span>
                        <Check size={13} />
                      </span>
                    </div>
                    <h2>{query ? "No jobs match your search." : filter === "inbox" ? "No new matches waiting." : "Your next opportunity starts here."}</h2>
                    <p>
                      {query
                        ? "Try a different title, employer, or location."
                        : filter === "inbox"
                          ? "Matches above your threshold appear here after each search."
                          : "Add a job you found, or connect job sources. Each role is compared with your verified experience."}
                    </p>
                    {filter !== "inbox" && (
                      <button className="button primary" onClick={() => (s.sources.length ? setAddOpen(true) : setTab("sources"))}>
                        <Plus size={17} />
                        {s.sources.length ? "Add a job manually" : "Add job sources"}
                      </button>
                    )}
                  </div>
                )}
                {visible.length > limit && (
                  <button className="button secondary full" onClick={() => setLimit(limit + PAGE)}>
                    Show more ({visible.length - limit} remaining)
                  </button>
                )}
              </section>
              <aside className="right-rail">
                <section className="focus-card">
                  <div className="section-label">
                    YOUR SEARCH FOCUS
                    <button aria-label="Edit search focus" onClick={() => setTab("settings")}>
                      <SlidersHorizontal size={15} />
                    </button>
                  </div>
                  <h3>Work at the intersection.</h3>
                  <div className="focus-tags">
                    {s.preferences.keywords.slice(0, 7).map((k) => (
                      <span key={k}>{k}</span>
                    ))}
                  </div>
                  <div className="focus-divider" />
                  <span className="muted-label">PREFERRED LOCATIONS</span>
                  <p>
                    {s.preferences.locations.join(" · ") || "Open to all locations"}
                    {s.preferences.location_mode === "strict" ? " (strict)" : ""}
                  </p>
                  <span className="muted-label">CONTRACT PREFERENCES</span>
                  <p>{s.preferences.contract_types.join(" · ")}</p>
                </section>
                <section className="rail-card">
                  <div className="section-label">
                    SEARCH STATUS <Radio size={16} />
                  </div>
                  <strong>
                    {active
                      ? "Collecting opportunities"
                      : s.schedule.enabled
                        ? s.scheduler.mode === "in-process" && s.scheduler.threads["career-scan"]
                          ? "Running automatically"
                          : s.scheduler.mode === "celery"
                            ? "Scheduled by the worker"
                            : "Schedule enabled, scheduler off"
                        : "Search on your terms"}
                  </strong>
                  <p>
                    {active && lastRun?.progress
                      ? lastRun.progress
                      : s.schedule.enabled
                        ? `Every ${s.preferences.scan_interval_hours} hours.`
                        : "Run a search whenever you’re ready. Enable scheduled searches in Preferences."}
                  </p>
                  {lastRun && (
                    <span className="last-run">
                      Last run: {lastRun.status} · {lastRun.added ?? 0} new · {lastRun.matched ?? 0} evaluated · {lastRun.alerts ?? 0} announced
                    </span>
                  )}
                </section>
                <div className="trust-note">
                  <ShieldCheck size={21} />
                  <p>Every application starts with your approval. Your experience stays factual.</p>
                </div>
              </aside>
            </div>
          </TabsContent>
          <TabsContent value="profile">
            <div className="two-columns">
              <section className="panel">
                <div className="panel-heading">
                  <h2>Master CV</h2>
                  <span className="tag">{verified} verified facts</span>
                </div>
                <label className="upload-zone">
                  <Upload size={28} />
                  <strong>{busy === "upload" ? "Reading your CV…" : "Upload your current CV"}</strong>
                  <span>DOCX, text PDF, TXT, or Markdown · up to 5 MB</span>
                  <input
                    type="file"
                    accept=".docx,.pdf,.txt,.md"
                    disabled={!!busy}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) upload(f);
                      e.target.value = "";
                    }}
                  />
                </label>
                <div className="or-label">or paste CV text</div>
                <textarea aria-label="CV text" rows={6} value={cvText} onChange={(e) => setCvText(e.target.value)} placeholder="Paste your employment history, projects, qualifications, and skills…" />
                <button
                  className="button secondary full"
                  disabled={!!busy || cvText.length < 40}
                  onClick={() =>
                    act(
                      "import",
                      async () => {
                        const p = await call<Profile>("/profile/text", "POST", { text: cvText });
                        setProfile(p);
                        track("cv_uploaded", { method: "text", facts: p.facts.length });
                        setCvText("");
                      },
                      "Imported. Verify the facts below.",
                    )
                  }
                >
                  Extract CV evidence
                </button>
                <p className="field-help">
                  {s.connections.ai ? "AI extracts facts with exact source quotes." : "Without an AI key, each line becomes a fact you can edit."} Re-importing replaces your evidence bank and discards stored evaluations. Scanned files need OCR before uploading.
                </p>
              </section>
              <section className="panel">
                <h2>Your profile</h2>
                <label className="field">
                  Full name
                  <input value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} placeholder="Your full name" />
                </label>
                <label className="field">
                  Professional headline
                  <input value={profile.headline} onChange={(e) => setProfile({ ...profile, headline: e.target.value })} placeholder="Data science, AI and hydro-climate specialist" />
                </label>
                <p className="field-help">Only the facts you verify will support application claims. Evaluations are kept unless verified evidence changes.</p>
                <button className="button primary" disabled={!!busy} onClick={() => act("profile", () => call("/profile", "PUT", profile), "Profile and evidence saved")}>
                  <Check size={17} />
                  Save verified profile
                </button>
              </section>
            </div>
            <section className="panel evidence-panel">
              <h2>Career evidence</h2>
              <p>Check each statement against your CV. Correct extraction errors before verifying.</p>
              {profile.facts.length > 0 && (
                <div className="evidence-toolbar">
                  <button type="button" className="button secondary" disabled={!!busy || profile.facts.every((f) => f.verified)} onClick={() => setProfile((c) => ({ ...c, facts: c.facts.map((f) => ({ ...f, verified: true })) }))}>
                    <Check size={17} /> Select all
                  </button>
                  <button type="button" className="button secondary" disabled={!!busy || !profile.facts.some((f) => f.verified)} onClick={() => setProfile((c) => ({ ...c, facts: c.facts.map((f) => ({ ...f, verified: false })) }))}>
                    Clear all
                  </button>
                  <span role="status" className="evidence-selection-count">
                    {profile.facts.filter((f) => f.verified).length} of {profile.facts.length} selected
                  </span>
                  <p className="evidence-selection-help">Select all after reviewing the statements, then click Save evidence.</p>
                </div>
              )}
              {profile.facts.length ? (
                profile.facts.map((f, i) => (
                  <div className="fact" key={f.id}>
                    <Checkbox aria-label={"Verify " + f.id} checked={f.verified} onCheckedChange={(v) => setProfile({ ...profile, facts: profile.facts.map((x, n) => (n === i ? { ...x, verified: v === true } : x)) })} />
                    <div>
                      <span className="fact-meta">
                        {f.id} · {f.category}
                      </span>
                      <textarea aria-label={"Evidence " + f.id} rows={2} value={f.text} onChange={(e) => setProfile({ ...profile, facts: profile.facts.map((x, n) => (n === i ? { ...x, text: e.target.value, verified: false } : x)) })} />
                      <details>
                        <summary>Source excerpt</summary>
                        <p>{f.source_quote}</p>
                      </details>
                    </div>
                  </div>
                ))
              ) : (
                <p className="muted-text">Upload or paste your CV to build your evidence bank.</p>
              )}
              {profile.facts.length > 0 && (
                <div className="sticky-save">
                  <span className={evidenceDirty ? "danger-text" : "muted-text"}>{evidenceDirty ? "Unsaved changes" : "All changes saved"}</span>
                  <button
                    className="button primary"
                    disabled={!!busy || !evidenceDirty}
                    onClick={() =>
                      act(
                        "profile",
                        async () => {
                          await call("/profile", "PUT", profile);
                          const v = profile.facts.filter((f) => f.verified).length;
                          if (v > 0) track("profile_completed", { verified_facts: v, total_facts: profile.facts.length });
                        },
                        "Evidence saved",
                      )
                    }
                  >
                    Save evidence
                  </button>
                </div>
              )}
            </section>
          </TabsContent>
          <TabsContent value="sources">
            <div className="two-columns">
              <section className="panel">
                <h2>Add a job source</h2>
                <label className="field">
                  Source
                  <Select
                    value={sourceKind}
                    onValueChange={(v) => {
                      setSourceKind(v);
                      setSourceTest(null);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(Object.keys(s.source_kinds).length ? s.source_kinds : Object.fromEntries(Object.keys(sourceHelp).map((k) => [k, k])))
                        .filter(([v]) => v !== "gmail" || isAdmin)
                        .map(([v, l]) => (
                          <SelectItem key={v} value={v}>
                            {l}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="field">
                  {sourceHelp[sourceKind]?.label ?? "Value"}
                  <input value={sourceValue} onChange={(e) => setSourceValue(e.target.value)} placeholder={sourceHelp[sourceKind]?.placeholder ?? ""} />
                </label>
                <p className="field-help">{sourceHelp[sourceKind]?.help}</p>
                {sourceKind === "imap" && !s.connections.imap && (
                  <p className="danger-text">
                    Connect your mailbox under <button className="text-button" onClick={() => setTab("account")}>Account</button> first.
                  </p>
                )}
                {(sourceKind === "page" || sourceKind === "imap" || sourceKind === "gmail") && !s.connections.ai && <p className="danger-text">This source needs your OpenAI API key (Account).</p>}
                <div className="detail-actions">
                  <button className="button secondary" disabled={!!busy} onClick={testSource}>
                    {busy === "test-source" ? <LoaderCircle className="spin" size={17} /> : <FlaskConical size={17} />}
                    Test source
                  </button>
                  <button className="button primary" disabled={!!busy} onClick={() => addSource(sourceKind, sourceValue)}>
                    <Plus size={17} />
                    Add source
                  </button>
                </div>
                <p className="field-help">
                  {s.sources.length} of {s.plan.sources} sources used on the {s.plan.label} plan.
                </p>
                {sourceTest && (
                  <div className="run-row">
                    <strong>{sourceTest.received} postings returned</strong>
                    {sourceTest.sample.map((x, i) => (
                      <p key={i} className="muted-text">
                        {x.title} · {x.company || "—"} · {x.location || "—"}
                      </p>
                    ))}
                    {sourceTest.received === 0 && <p className="muted-text">Nothing came back. Check the identifier or query.</p>}
                    {sourceTest.sample.length === 0 && sourceTest.received > 0 && <p className="muted-text">All returned postings are already in your workspace.</p>}
                  </div>
                )}
              </section>
              <section className="panel">
                <h2>Suggested for your field</h2>
                {s.suggested_sources.map((x) => {
                  const present = s.sources.some((src) => src.kind === x.kind && src.value === x.value);
                  return (
                    <div className="source-row" key={x.kind + x.value}>
                      <Radio size={19} />
                      <div>
                        <strong>{x.label}</strong>
                        <p>{x.note}</p>
                      </div>
                      {present ? (
                        <span className="tag tag-green">Added</span>
                      ) : (
                        <button className="text-button" disabled={!!busy} onClick={() => addSource(x.kind, x.value)}>
                          Add <Plus size={15} />
                        </button>
                      )}
                    </div>
                  );
                })}
                <p className="field-help">
                  LinkedIn: create saved searches with email alerts, label those emails <strong>JobsFindAI</strong> in your mailbox, connect the mailbox under Account, then add the mailbox source. Incomplete email excerpts stay excerpts; paste the full posting before preparing a detailed application.
                </p>
              </section>
            </div>
            <section className="panel">
              <h2>Connected sources</h2>
              {s.sources.length ? (
                s.sources.map((src) => (
                  <div className="source-row" key={src.id}>
                    <Radio size={19} />
                    <div>
                      <strong>{s.source_kinds[src.kind] ?? src.kind}</strong>
                      <p>{src.value || (src.kind === "imap" || src.kind === "gmail" ? "JobsFindAI label" : "default query")}</p>
                    </div>
                    <Switch aria-label="Enable source" checked={src.enabled} onCheckedChange={(v) => act("toggle-source", () => call("/sources/" + src.id, "PUT", { enabled: v }), v ? "Source enabled" : "Source paused")} />
                    <button className="icon-button" aria-label="Remove source" onClick={() => act("remove", () => call("/sources/" + src.id, "DELETE"), "Source removed")}>
                      <X size={18} />
                    </button>
                  </div>
                ))
              ) : (
                <p className="muted-text">No feeds yet. Add your first source above.</p>
              )}
            </section>
            <section className="panel">
              <h2>Search activity</h2>
              {s.runs.length ? (
                s.runs.map((r) => (
                  <div className="run-row" key={r.id}>
                    <strong>
                      {new Date(r.created).toLocaleString()} · {r.status}
                      {r.trigger === "scheduled" ? " · automatic" : ""}
                    </strong>
                    <p>
                      {r.added ?? 0} new jobs · {r.matched ?? 0} evaluated · {r.alerts ?? 0} announced
                      {r.archived ? ` · ${r.archived} archived` : ""}
                      {r.delivered && Object.keys(r.delivered).filter((k) => k !== "inapp").length
                        ? " · " +
                          Object.entries(r.delivered)
                            .filter(([k]) => k !== "inapp")
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(", ")
                        : ""}
                    </p>
                    {r.status === "running" && r.progress && <p className="muted-text">{r.progress}</p>}
                    {r.error && <p className="danger-text">{r.error}</p>}
                    {r.sources?.map((x, i) => (
                      <p key={i} className={x.status === "failed" ? "danger-text" : "muted-text"}>
                        {x.name}: {x.error || `${x.received ?? 0} received · ${x.relevant ?? 0} relevant · ${x.added ?? 0} new${x.pages ? ` · ${x.pages} pages read` : ""}`}
                      </p>
                    ))}
                    {Array.from(new Set(r.warnings ?? [])).map((w) => (
                      <p key={w} className="danger-text">
                        {w}
                      </p>
                    ))}
                  </div>
                ))
              ) : (
                <p className="muted-text">Search results and source errors will appear here.</p>
              )}
            </section>
          </TabsContent>
          <TabsContent value="applications">
            {s.applications.length ? (
              <div className="applications-grid">
                {s.applications.map((a) => (
                  <article className="panel application-card" key={a.id}>
                    <span className="tag">{a.status === "review" ? "Ready for your review" : a.status}</span>
                    <h2>{a.title}</h2>
                    <p>{a.company}</p>
                    {a.error && <p className="danger-text">{a.error}</p>}
                    {a.review_notes?.map((n, i) => (
                      <p key={i} className="muted-text">
                        {n}
                      </p>
                    ))}
                    <div className="application-actions">
                      {a.package ? (
                        <>
                          <button
                            className="button primary"
                            onClick={() => {
                              setEditing(a);
                              setDraft(structuredClone(a.package!));
                            }}
                          >
                            Review & edit
                          </button>
                          <button className="button secondary" onClick={() => download(a)}>
                            <Download size={16} />
                            Export ZIP
                          </button>
                        </>
                      ) : (
                        <button
                          className="button secondary"
                          disabled={!!busy}
                          onClick={() => {
                            const j = s.jobs.find((j) => j.id === a.job_id);
                            if (j) prepare(j);
                          }}
                        >
                          {a.status === "failed" ? "Retry preparation" : a.status === "preparing" ? "Preparing…" : "Check / retry"}
                        </button>
                      )}
                    </div>
                    <p className="field-help">{a.package ? "DOCX, PDF, checklist, and evidence references." : "Drafting, factual review and one revision pass usually take a few minutes. Interrupted preparations can be retried after 10 minutes."}</p>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-jobs application-empty">
                <FileText size={34} />
                <h2>A stronger application begins with a good fit.</h2>
                <p>Review a job and choose Prepare application. Your tailored documents will appear here.</p>
                <button className="button secondary" onClick={() => setTab("opportunities")}>
                  Browse opportunities <ChevronRight size={16} />
                </button>
              </div>
            )}
            <p className="field-help">
              {s.plan.packages_used} of {s.plan.packages_per_month} application packages used this month on the {s.plan.label} plan.
            </p>
          </TabsContent>
          <TabsContent value="settings">
            <div className="two-columns">
              <section className="panel">
                <h2>Search preferences</h2>
                {(
                  [
                    ["keywords", "Fields and keywords"],
                    ["locations", "Preferred locations"],
                    ["contract_types", "Contract types"],
                    ["excluded_keywords", "Exclude these terms"],
                  ] as const
                ).map(([k, l]) => (
                  <label className="field" key={k}>
                    {l}
                    <input value={prefs[k].join(", ")} onChange={(e) => setPrefs({ ...prefs, [k]: e.target.value.split(",").map((v) => v.trim()) })} />
                    <span className="field-help">Separate entries with commas. Keywords match any word form (data science ↔ data scientist).</span>
                  </label>
                ))}
                <label className="field">
                  Location handling
                  <Select value={prefs.location_mode} onValueChange={(v) => setPrefs({ ...prefs, location_mode: v })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="soft">Rank preferred locations first</SelectItem>
                      <SelectItem value="strict">Only keep preferred locations</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
                <label className="field">
                  Minimum alert score
                  <input type="number" min={0} max={100} value={prefs.min_score} onChange={(e) => setPrefs({ ...prefs, min_score: Number(e.target.value) })} />
                </label>
                <button className="button primary" disabled={!!busy} onClick={savePrefs}>
                  Save preferences
                </button>
                <p className="field-help">Changing keywords, locations or contract types re-evaluates stored jobs on the next search. Other settings do not.</p>
              </section>
              <div>
                <section className="panel">
                  <h2>Notifications</h2>
                  <div className="switch-row">
                    <div>
                      <strong>Send matching job alerts</strong>
                      <p>Only AI-reviewed matches above your threshold. The in-app inbox is always on.</p>
                    </div>
                    <Switch aria-label="Enable alerts" checked={prefs.alerts_enabled} onCheckedChange={(v) => setPrefs({ ...prefs, alerts_enabled: v })} />
                  </div>
                  {["telegram", "email", ...(isAdmin ? ["whatsapp"] : [])].map((c) => (
                    <div className="channel-row" key={c}>
                      <Checkbox aria-label={"Use " + c} checked={prefs.notify_channels.includes(c)} onCheckedChange={(v) => setPrefs({ ...prefs, notify_channels: v ? [...prefs.notify_channels, c] : prefs.notify_channels.filter((x) => x !== c) })} />
                      <strong>{c === "whatsapp" ? "WhatsApp" : c[0].toUpperCase() + c.slice(1)}</strong>
                      <span className={"tag " + (s.connections[c] ? "tag-green" : "")}>
                        {s.connections[c] ? "Ready" : c === "telegram" && s.telegram.bot_configured ? "Link your chat (Account)" : c === "email" ? "Not offered on this server" : "Not configured"}
                      </span>
                      {s.connections[c] && (
                        <button className="text-button" disabled={!!busy} onClick={() => act("test-" + c, () => call("/notify/test/" + c, "POST"), "Test alert sent")}>
                          <Send size={14} /> Send test
                        </button>
                      )}
                    </div>
                  ))}
                  <label className="field">
                    Delivery
                    <Select value={prefs.alert_mode} onValueChange={(v) => setPrefs({ ...prefs, alert_mode: v })}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="each">One message per job (with Interested / Skip)</SelectItem>
                        <SelectItem value="digest">One digest per search</SelectItem>
                      </SelectContent>
                    </Select>
                  </label>
                  <label className="channel-row" style={{ gap: 8 }}>
                    <Checkbox checked={prefs.email_digest} onCheckedChange={(v) => setPrefs({ ...prefs, email_digest: v === true })} />
                    <span className="muted-text">Email: one summary per search instead of one email per job</span>
                  </label>
                  <button className="text-button" onClick={savePrefs}>
                    Save notification choices <Check size={16} />
                  </button>
                </section>
                <section className="panel">
                  <h2>Scheduled searches</h2>
                  <div className="switch-row">
                    <div>
                      <strong>Search automatically</strong>
                      <p>{s.plan.schedule ? "Runs on the server at your interval, even when you are offline." : "Not included in your plan."}</p>
                    </div>
                    <Switch aria-label="Enable scheduled searches" disabled={!s.plan.schedule} checked={s.schedule.enabled} onCheckedChange={(v) => act("schedule", () => call("/schedule", "PUT", { enabled: v }), v ? "Schedule enabled" : "Schedule paused")} />
                  </div>
                  <label className="field">
                    Interval (hours)
                    <input type="number" min={1} max={48} value={prefs.scan_interval_hours} onChange={(e) => setPrefs({ ...prefs, scan_interval_hours: Number(e.target.value) })} />
                    <span className="field-help">Saved with preferences. Each search evaluates up to {s.plan.evaluations_per_run} new postings with your AI key.</span>
                  </label>
                </section>
              </div>
            </div>
          </TabsContent>
          <TabsContent value="account">
            <div className="two-columns">
              <div>
                <section className="panel">
                  <h2>
                    <KeyRound size={18} /> OpenAI API key
                  </h2>
                  <span className={"tag " + (s.user.has_openai_key ? "tag-green" : s.connections.ai ? "tag-green" : "")}>
                    {s.user.has_openai_key ? "Your key is set" : isAdmin && s.connections.ai ? "Using the server key" : s.connections.ai_sponsored ? "AI included in your beta seat" : "Not set"}
                  </span>
                  {s.connections.ai_sponsored ? (
                    <p className="field-help">
                      Your seat includes AI usage paid by the founder: up to {s.plan.evaluations_per_run} evaluations per search, {s.plan.evaluations_per_month ?? "unlimited"} per month
                      {typeof s.plan.evaluations_used === "number" ? ` (${s.plan.evaluations_used} used this month)` : ""} and {s.plan.packages_per_month} application packages a month. Add your own key below at any time to lift those limits.
                    </p>
                  ) : (
                    <p className="field-help">Evaluations and drafts run on your own key, so you pay OpenAI directly for what you use. The key is stored encrypted and never shown again.</p>
                  )}
                  <label className="field">
                    API key
                    <input type="password" autoComplete="off" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-…" />
                  </label>
                  <div className="detail-actions">
                    <button
                      className="button primary"
                      disabled={!!busy || apiKey.length < 20}
                      onClick={() =>
                        act(
                          "key",
                          async () => {
                            await call("/account/openai_key", "PUT", { key: apiKey });
                            setApiKey("");
                          },
                          "Key verified and saved",
                        )
                      }
                    >
                      {busy === "key" ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />} Save key
                    </button>
                    {s.user.has_openai_key && (
                      <button className="button secondary" disabled={!!busy} onClick={() => act("key-remove", () => call("/account/openai_key", "DELETE"), "Key removed")}>
                        Remove
                      </button>
                    )}
                  </div>
                </section>
                <section className="panel">
                  <h2>
                    <Mail size={18} /> Mailbox for email alerts
                  </h2>
                  <span className={"tag " + (s.user.has_imap ? "tag-green" : "")}>{s.user.has_imap ? "Connected" : "Not connected"}</span>
                  <p className="field-help">
                    Forward or filter LinkedIn, Devex, UNjobs or ReliefWeb alerts into a <strong>JobsFindAI</strong> label, then connect the mailbox here with an app password (Gmail: Google Account → Security → 2-Step Verification → App passwords). Only that label is read.
                  </p>
                  <div className="two-fields">
                    <label className="field">
                      IMAP host
                      <input value={imap.host} onChange={(e) => setImap({ ...imap, host: e.target.value })} placeholder="imap.gmail.com" />
                    </label>
                    <label className="field">
                      Port
                      <input type="number" value={imap.port} onChange={(e) => setImap({ ...imap, port: Number(e.target.value) })} />
                    </label>
                  </div>
                  <div className="two-fields">
                    <label className="field">
                      Email address
                      <input value={imap.username} onChange={(e) => setImap({ ...imap, username: e.target.value })} autoComplete="off" />
                    </label>
                    <label className="field">
                      App password
                      <input type="password" value={imap.password} onChange={(e) => setImap({ ...imap, password: e.target.value })} autoComplete="off" />
                    </label>
                  </div>
                  <label className="field">
                    Label or folder
                    <input value={imap.folder} onChange={(e) => setImap({ ...imap, folder: e.target.value })} />
                  </label>
                  <div className="detail-actions">
                    <button
                      className="button primary"
                      disabled={!!busy || !imap.username || !imap.password}
                      onClick={() =>
                        act(
                          "imap",
                          async () => {
                            const r = await call<{ messages_in_folder: number }>("/account/imap", "PUT", imap);
                            setImap({ ...imap, password: "" });
                            toast.success(`Connected. ${r.messages_in_folder} messages in the label.`);
                          },
                        )
                      }
                    >
                      {busy === "imap" ? <LoaderCircle className="spin" size={17} /> : <Check size={17} />} Connect mailbox
                    </button>
                    {s.user.has_imap && (
                      <button className="button secondary" disabled={!!busy} onClick={() => act("imap-remove", () => call("/account/imap", "DELETE"), "Mailbox disconnected")}>
                        Disconnect
                      </button>
                    )}
                  </div>
                </section>
              </div>
              <div>
                <section className="panel">
                  <h2>Telegram</h2>
                  {!s.telegram.bot_configured ? (
                    <p className="field-help">Telegram alerts are not enabled on this server.</p>
                  ) : s.telegram.linked ? (
                    <>
                      <span className="tag tag-green">Linked{s.telegram.username ? " to @" + s.telegram.username : ""}</span>
                      <p className="field-help">Alerts go to your private chat. Interested / Skip buttons update your shortlist here.</p>
                      {!s.telegram.via_env && (
                        <button className="text-button" onClick={() => act("unlink", () => call("/telegram/link", "DELETE"), "Telegram unlinked")}>
                          Unlink <X size={15} />
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      {linkCode ? (
                        <div className="run-row">
                          <strong>Send this code to @{linkCode.bot_username || "the bot"} on Telegram:</strong>
                          <p style={{ fontSize: "1.6rem", letterSpacing: "0.2em" }}>{linkCode.code}</p>
                          <p className="muted-text">Open the bot, press Start, and send the code as a message. It expires in 15 minutes. This page updates when the link succeeds.</p>
                        </div>
                      ) : (
                        <p className="field-help">Link your own Telegram account to receive alerts with Interested / Skip buttons.</p>
                      )}
                      <button className="button primary" disabled={!!busy} onClick={() => act("link", async () => {
                            track("telegram_link_started", {});
                            setLinkCode(await call<{ code: string; bot_username: string }>("/telegram/link", "POST"));
                          })}>
                        <Link2 size={17} /> {linkCode ? "New code" : "Link Telegram"}
                      </button>
                    </>
                  )}
                </section>
                <section className="panel">
                  <h2>Profile and password</h2>
                  <p className="field-help">
                    Signed in as <strong data-ph-mask>{s.user.email}</strong> · {s.plan.label} plan{isAdmin ? " · owner" : ""}
                  </p>
                  <label className="field">
                    Display name
                    <input value={accountName} onChange={(e) => setAccountName(e.target.value)} />
                  </label>
                  <button className="button secondary" disabled={!!busy} onClick={() => act("name", () => call("/account", "PUT", { name: accountName }), "Saved")}>
                    Save name
                  </button>
                  <div className="two-fields" style={{ marginTop: 16 }}>
                    <label className="field">
                      Current password
                      <input type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
                    </label>
                    <label className="field">
                      New password
                      <input type="password" value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} autoComplete="new-password" />
                    </label>
                  </div>
                  <button
                    className="button secondary"
                    disabled={!!busy || pw.new.length < 10 || !pw.current}
                    onClick={() =>
                      act(
                        "password",
                        async () => {
                          await call("/account/password", "PUT", pw);
                          setPw({ current: "", new: "" });
                        },
                        "Password changed",
                      )
                    }
                  >
                    Change password
                  </button>
                  <div className="detail-actions" style={{ marginTop: 16 }}>
                    <button className="text-button" onClick={signOut}>
                      <LogOut size={15} /> Sign out
                    </button>
                  </div>
                </section>
              </div>
            </div>
          </TabsContent>
          {isAdmin && (
            <TabsContent value="admin">
              {overview ? (
                <>
                  <div className="stats">
                    {[
                      [overview.totals.users, "Accounts", "In the beta"],
                      [overview.totals.activated, "Activated", "Verified CV and a source"],
                      [overview.totals.drafted, "Drafting", "Prepared an application"],
                      [overview.totals.with_key, "With own AI key", overview.totals.telegram + " linked Telegram"],
                      [overview.totals.sponsored ?? 0, "Sponsored seats", `of ${overview.totals.sponsored_seats ?? 0} · ${overview.totals.sponsored_evaluations_this_month ?? 0} evaluations on your key this month`],
                      [overview.totals.server_key_calls_this_month ?? 0, "Model calls on your key", `this month · cap ${overview.totals.server_key_monthly_cap || "none"}`],
                    ].map(([n, l, m]) => (
                      <div key={String(l)}>
                        <span>{l}</span>
                        <strong>{String(n).padStart(2, "0")}</strong>
                        <small>{m}</small>
                      </div>
                    ))}
                  </div>
                  <section className="panel">
                    <h2>Invitations</h2>
                    <div className="two-fields">
                      <label className="field">
                        How many
                        <input type="number" min={1} max={50} value={inviteCount} onChange={(e) => setInviteCount(Number(e.target.value))} />
                      </label>
                      <label className="field">
                        Note (who they are for)
                        <input value={inviteNote} onChange={(e) => setInviteNote(e.target.value)} />
                      </label>
                    </div>
                    <button
                      className="button primary"
                      disabled={!!busy}
                      onClick={() =>
                        act("invites", async () => {
                          const r = await call<{ codes: string[] }>("/admin/invites", "POST", { count: inviteCount, note: inviteNote });
                          setNewCodes(r.codes);
                          setOverview(await call<Overview>("/admin/overview"));
                        })
                      }
                    >
                      <Plus size={17} /> Generate codes
                    </button>
                    {newCodes.length > 0 && (
                      <div className="run-row">
                        <strong>New codes (share one per person)</strong>
                        {newCodes.map((c) => (
                          <p key={c} className="muted-text">
                            {window.location.origin}/app/?invite={c}
                          </p>
                        ))}
                      </div>
                    )}
                    <p className="field-help">
                      {overview.invites.filter((i) => !i.used_by).length} unused · {overview.invites.filter((i) => i.used_by).length} used
                    </p>
                  </section>
                  {overview.waitlist && overview.waitlist.length > 0 && (
                    <section className="panel">
                      <div className="panel-head">
                        <h2>Invitation requests ({overview.waitlist.length})</h2>
                        {overview.waitlist.some((w) => !w.invited) && (
                          <button
                            className="button secondary"
                            disabled={busy === "invite-all"}
                            onClick={() =>
                              act("invite-all", async () => {
                                const r = await call<{ results: { email: string; status: string }[]; email_configured: boolean }>("/admin/waitlist/invite", "POST", { emails: overview.waitlist.filter((w) => !w.invited).map((w) => w.email) });
                                const sent = r.results.filter((x) => x.status === "sent").length;
                                const failed = r.results.filter((x) => x.status === "email_failed").length;
                                toast[failed ? "error" : "success"](r.email_configured ? `${sent} invitation${sent === 1 ? "" : "s"} emailed${failed ? `, ${failed} failed (codes created, share them by hand)` : ""}.` : "Codes created. Email is not configured on this server, so share the links by hand.");
                                setOverview(await call<Overview>("/admin/overview"));
                              })
                            }
                          >
                            Invite everyone pending
                          </button>
                        )}
                      </div>
                      <p className="field-help">From the landing page. Sending an invitation creates a personal code and emails the sign-up link.</p>
                      {overview.waitlist.map((w) => (
                        <div className="source-row" key={w.email}>
                          <UserRound size={18} />
                          <div>
                            <strong>{w.name || w.email}</strong>
                            <p>
                              {w.email}
                              {w.note ? " · " + w.note : ""} · {new Date(w.created).toLocaleDateString()}
                              {w.invited ? ` · invited ${new Date(w.invited).toLocaleDateString()}${w.code ? " · code " + w.code : ""}` : ""}
                            </p>
                          </div>
                          <button
                            className="text-button"
                            disabled={busy === "invite-" + w.email}
                            onClick={() =>
                              act("invite-" + w.email, async () => {
                                const r = await call<{ results: { email: string; status: string; link?: string }[]; email_configured: boolean }>("/admin/waitlist/invite", "POST", { emails: [w.email] });
                                const x = r.results[0];
                                if (x.status === "sent") toast.success("Invitation emailed to " + w.email + ".");
                                else if (x.status === "already_registered") toast.success(w.email + " already has an account.");
                                else if (x.status === "email_failed") toast.error("Email failed; share this link by hand: " + x.link);
                                else toast.success("Code created. Share this link: " + x.link);
                                setOverview(await call<Overview>("/admin/overview"));
                              })
                            }
                          >
                            {w.invited ? "Resend invitation" : "Send invitation"}
                          </button>
                        </div>
                      ))}
                    </section>
                  )}
                  <section className="panel">
                    <h2>Accounts</h2>
                    <div className="table-scroll">
                      <table className="admin-table">
                        <thead>
                          <tr>
                            <th>Email</th>
                            <th>Plan</th>
                            <th>Key</th>
                            <th>CV facts</th>
                            <th>Sources</th>
                            <th>Searches</th>
                            <th>Evaluated</th>
                            <th>Packages</th>
                            <th>Telegram</th>
                            <th>Organisation</th>
                            <th>Last active</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {overview.users.map((u) => (
                            <tr key={u.id}>
                              <td>
                                {u.email}
                                {u.role === "admin" ? " (owner)" : ""}
                                {u.name ? <br /> : null}
                                <small>{u.name}</small>
                              </td>
                              <td>
                                <Select
                                  value={u.plan}
                                  onValueChange={(v) =>
                                    act("plan", async () => {
                                      await call(`/admin/users/${u.id}`, "PUT", { plan: v });
                                      setOverview(await call<Overview>("/admin/overview"));
                                    })
                                  }
                                >
                                  <SelectTrigger>
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {Object.entries(overview.plans).map(([id, p]) => (
                                      <SelectItem key={id} value={id}>
                                        {p.label}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </td>
                              <td>
                                {u.has_openai_key ? "own" : u.sponsored ? "sponsored" : "—"}
                                {u.role !== "admin" && (
                                  <>
                                    <br />
                                    <button
                                      className="text-button"
                                      onClick={() =>
                                        act("sponsor", async () => {
                                          await call(`/admin/users/${u.id}`, "PUT", { sponsored: !u.sponsored });
                                          setOverview(await call<Overview>("/admin/overview"));
                                        })
                                      }
                                    >
                                      {u.sponsored ? "Unsponsor" : "Sponsor"}
                                    </button>
                                  </>
                                )}
                              </td>
                              <td>{u.verified_facts}</td>
                              <td>{u.sources}</td>
                              <td>{u.searches}</td>
                              <td>
                                {u.evaluated}
                                <br />
                                <small>{u.evaluations_this_month ?? 0} this month</small>
                              </td>
                              <td>
                                {u.packages}/{u.packages_requested}
                              </td>
                              <td>{u.telegram_linked ? "✓" : "—"}</td>
                              <td>
                                <input
                                  className="cell-input"
                                  defaultValue={u.organisation ?? ""}
                                  placeholder="—"
                                  maxLength={80}
                                  aria-label={"Organisation for " + u.email}
                                  onBlur={(e) => {
                                    const v = e.target.value.trim();
                                    if (v === (u.organisation ?? "")) return;
                                    act("organisation", async () => {
                                      await call(`/admin/users/${u.id}`, "PUT", { organisation: v });
                                      setOverview(await call<Overview>("/admin/overview"));
                                    });
                                  }}
                                />
                              </td>
                              <td>{u.last_active ? new Date(u.last_active).toLocaleDateString() : "—"}</td>
                              <td>
                                <button
                                  className="text-button"
                                  onClick={() =>
                                    act("reset", async () => {
                                      const r = await call<{ temporary_password: string }>(`/admin/users/${u.id}/reset`, "POST");
                                      window.prompt("Temporary password for " + u.email + " (share it privately):", r.temporary_password);
                                    })
                                  }
                                >
                                  Reset password
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                </>
              ) : (
                <p className="muted-text">Loading…</p>
              )}
            </TabsContent>
          )}
          <footer className="footer">
            <span>{s.app_name} · A personal approach to your next role.</span>
            <span>
              <a href="/privacy.html" target="_blank" rel="noreferrer">
                Privacy
              </a>{" "}
              ·{" "}
              <a href="/terms.html" target="_blank" rel="noreferrer">
                Terms
              </a>
            </span>
          </footer>
        </main>
      </Tabs>
      {flag("assistant-widget") && <Assistant />}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="wide-dialog">
          <DialogHeader>
            <DialogTitle>Add an opportunity</DialogTitle>
            <DialogDescription>Paste the full posting to evaluate its requirements.</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              act(
                "add",
                async () => {
                  const result = await call<Job>("/jobs", "POST", {
                    title: f.get("title"),
                    company: f.get("company"),
                    location: f.get("location") || "Not specified",
                    url: f.get("url") || "",
                    description: f.get("description"),
                    deadline: f.get("deadline") || null,
                    source: "Manual",
                  });
                  setAddOpen(false);
                  setSelected(result.id);
                },
                "Job added",
              );
            }}
          >
            <div className="two-fields">
              <label className="field">
                Job title
                <input name="title" required minLength={2} />
              </label>
              <label className="field">
                Employer
                <input name="company" />
              </label>
            </div>
            <div className="two-fields">
              <label className="field">
                Location
                <input name="location" />
              </label>
              <label className="field">
                Deadline
                <input name="deadline" type="date" />
              </label>
            </div>
            <label className="field">
              Posting URL
              <input name="url" type="url" />
            </label>
            <label className="field">
              Full job description
              <textarea name="description" required minLength={30} maxLength={60000} rows={8} />
            </label>
            <button className="button primary" disabled={!!busy}>
              Save opportunity
            </button>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!selected}
        onOpenChange={(v) => {
          if (!v) setSelected(null);
        }}
      >
        <DialogContent className="job-dialog">
          <DialogHeader>
            <DialogDescription>
              {job?.company} · {job?.location} · {job?.source}
            </DialogDescription>
            <DialogTitle>{job?.title ?? "Loading…"}</DialogTitle>
          </DialogHeader>
          {job && (
            <>
              <div className="detail-actions">
                <button className="button primary" disabled={!!busy || job.expired} onClick={() => prepare(job)}>
                  <FileText size={17} />
                  Prepare application
                </button>
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={() =>
                    act(
                      "match",
                      async () => {
                        const started = Date.now();
                        track("match_analysis_started", { source: job.source, reevaluate: !!job.match });
                        const r = await call<Job>(`/jobs/${job.id}/match`, "POST");
                        track("match_analysis_completed", { seconds: Math.round((Date.now() - started) / 1000), score: r.match?.score ?? null, mode: r.match?.mode });
                      },
                      "Match updated",
                    )
                  }
                >
                  {busy === "match" ? <LoaderCircle className="spin" size={17} /> : <Search size={17} />}
                  {job.match ? "Re-evaluate match" : "Evaluate match"}
                </button>
                <button className="icon-button" aria-label="Save to shortlist" onClick={() => decide(job, "saved")}>
                  <Bookmark size={18} fill={job.status === "saved" ? "currentColor" : "none"} />
                </button>
              </div>
              {job.expired && <p className="danger-text">The listed deadline has passed.</p>}
              {job.match && (
                <section className="match-detail">
                  <div className="panel-heading">
                    <h3>
                      {job.match.score}/100 · {job.match.mode === "keyword" ? "Keyword overlap" : "Relevance"}
                    </h3>
                    <span className="tag">Not a hiring probability</span>
                  </div>
                  <p>{job.match.summary}</p>
                  {job.match.strengths.length > 0 && (
                    <>
                      <h4>Why you fit</h4>
                      <ul>
                        {job.match.strengths.map((g) => (
                          <li key={g}>{g}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {job.match.requirements.length > 0 && <h4>Requirements</h4>}
                  {job.match.requirements.map((r, i) => (
                    <div className="requirement" key={i}>
                      <span className={"requirement-status " + r.status}>{r.status.replace("_", " ")}</span>
                      <div>
                        <strong>{r.requirement}</strong>
                        <p>{r.reason}</p>
                        <small>
                          {r.mandatory ? "Mandatory" : "Preferred"} {r.evidence_ids.length ? "· Evidence: " + r.evidence_ids.join(", ") : ""}
                        </small>
                      </div>
                    </div>
                  ))}
                  {job.match.gaps.length > 0 && (
                    <>
                      <h4>Gaps and unknowns</h4>
                      <ul>
                        {job.match.gaps.map((g) => (
                          <li key={g}>{g}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </section>
              )}
              <div className="panel-heading">
                <h3>Original posting</h3>
                {link(job.url) && (
                  <a className="text-button" href={link(job.url)} target="_blank" rel="noreferrer">
                    Open source <ArrowUpRight size={15} />
                  </a>
                )}
              </div>
              {s.alerts.filter((a) => a.job_id === job.id && a.channel !== "inapp").length > 0 && (
                <p className="field-help">
                  Alerts:{" "}
                  {s.alerts
                    .filter((a) => a.job_id === job.id && a.channel !== "inapp")
                    .map((a) => (
                      <span key={a.id}>
                        {a.channel} {a.status.replace("_", " ")}
                        {["delivery_unknown", "failed"].includes(a.status) && (
                          <>
                            {" "}
                            <button
                              className="text-button"
                              disabled={!!busy}
                              onClick={() =>
                                act("resend", async () => {
                                  const r = await call<{ status: string }>(`/alerts/${a.id}/resend`, "POST");
                                  if (r.status === "accepted") toast.success("The provider accepted the alert.");
                                  else toast.warning("Delivery is still uncertain. The provider did not confirm the message.");
                                })
                              }
                            >
                              Resend
                            </button>
                          </>
                        )}{" "}
                      </span>
                    ))}
                </p>
              )}
              <p className="posting-text">{job.description ?? job.description_preview ?? "Loading…"}</p>
              <div className="detail-bottom">
                <span>
                  {job.posted ? "Posted " + date(job.posted, "") + " · " : ""}
                  {date(job.deadline)}
                </span>
                <button className="text-button" onClick={() => decide(job, "applied")}>
                  Mark applied <Check size={16} />
                </button>
                <button className="text-button" onClick={() => decide(job, "skipped")}>
                  Skip <X size={16} />
                </button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!editing}
        onOpenChange={(v) => {
          if (!v) {
            setEditing(null);
            setDraft(null);
          }
        }}
      >
        <DialogContent className="package-dialog">
          <DialogHeader>
            <DialogTitle>Review application documents</DialogTitle>
            <DialogDescription>{editing?.title} · Your master evidence stays separate.</DialogDescription>
          </DialogHeader>
          {draft && editing && (
            <>
              <Tabs defaultValue="cv">
                <TabsList>
                  <TabsTrigger value="cv">CV</TabsTrigger>
                  <TabsTrigger value="letter">Cover letter</TabsTrigger>
                  <TabsTrigger value="answers">Answers</TabsTrigger>
                  <TabsTrigger value="extras">Checklist & extras</TabsTrigger>
                </TabsList>
                {(
                  [
                    ["cv", "cv"],
                    ["letter", "cover_letter"],
                  ] as const
                ).map(([t, k]) => (
                  <TabsContent key={k} value={t}>
                    <h3>{draft[k].title}</h3>
                    {draft[k].paragraphs.map((p, i) => (
                      <label className="field" key={i}>
                        <span className="fact-meta">{p.evidence_ids.length ? "Evidence: " + p.evidence_ids.join(", ") : "Review this wording"}</span>
                        <textarea rows={3} value={p.text} onChange={(e) => setDraft({ ...draft, [k]: { ...draft[k], paragraphs: draft[k].paragraphs.map((x, n) => (i === n ? { ...x, text: e.target.value } : x)) } })} />
                      </label>
                    ))}
                  </TabsContent>
                ))}
                <TabsContent value="answers">
                  {draft.answers.length ? (
                    draft.answers.map((a, i) => (
                      <label className="field" key={i}>
                        {a.question}
                        <textarea rows={5} value={a.answer} onChange={(e) => setDraft({ ...draft, answers: draft.answers.map((x, n) => (i === n ? { ...x, answer: e.target.value } : x)) })} />
                        <span className={a.character_limit && a.answer.length > a.character_limit ? "danger-text" : "field-help"}>
                          {a.answer.length}
                          {a.character_limit ? " / " + a.character_limit : ""} characters
                        </span>
                      </label>
                    ))
                  ) : (
                    <p>No screening questions were found in the supplied posting.</p>
                  )}
                </TabsContent>
                <TabsContent value="extras">
                  <h3>Required documents</h3>
                  <ul>
                    {draft.checklist.map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                  <h3>Information to complete</h3>
                  <ul>
                    {draft.missing_information.map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                  {editing.review_notes && editing.review_notes.length > 0 && (
                    <>
                      <h3>Reviewer notes</h3>
                      <ul>
                        {editing.review_notes.map((x, i) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {draft.additional_documents.map((d, i) => (
                    <section key={i}>
                      <h3>{d.title}</h3>
                      {d.paragraphs.map((p, n) => (
                        <label className="field" key={n}>
                          Paragraph {n + 1}
                          <textarea
                            rows={4}
                            value={p.text}
                            onChange={(e) =>
                              setDraft({
                                ...draft,
                                additional_documents: draft.additional_documents.map((x, j) => (i === j ? { ...x, paragraphs: x.paragraphs.map((y, k) => (n === k ? { ...y, text: e.target.value } : y)) } : x)),
                              })
                            }
                          />
                        </label>
                      ))}
                    </section>
                  ))}
                </TabsContent>
              </Tabs>
              <div className="detail-actions">
                <button className="button secondary" disabled={!!busy} onClick={() => act("draft", () => call("/applications/" + editing.id, "PUT", { package: draft, status: "review" }), "Draft saved")}>
                  Save draft
                </button>
                <button
                  className="button primary"
                  disabled={!!busy}
                  onClick={() =>
                    act(
                      "ready",
                      async () => {
                        await call("/applications/" + editing.id, "PUT", { package: draft, status: "ready" });
                        track("application_ready", {});
                        setEditing(null);
                      },
                      "Marked ready. Nothing has been submitted.",
                    )
                  }
                >
                  <Check size={17} />
                  Mark ready
                </button>
              </div>
              <p className="field-help">Review facts, formatting, and employer requirements before submitting externally.</p>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
