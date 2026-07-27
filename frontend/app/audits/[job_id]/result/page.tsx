"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getAuditDetails, getAuditResult, getAuditPdf } from '@/lib/actions';
import { Popover, PopoverButton, PopoverPanel } from '@headlessui/react';

// ── Types ────────────────────────────────────────────────────────────────────

interface LanguageGap {
  language: string;
  market: string;
  strength: "strong" | "medium";
  reason: string;
  regulatory: boolean;
}

interface AuditMeta {
  company_name: string;
  url: string;
  created_at: string;
}

interface UiPillar {
  headline: string;
  findings: string[];
  recommendations: string[];
}

interface UiContent {
  executive_summary: string[];
  pillar_1: UiPillar;
  pillar_2: UiPillar;
  pillar_3: UiPillar;
  pillar_4: UiPillar;
  competitive_landscape: {
    summary: string;
    client_advantages: string[];
    client_gaps: string[];
  };
  top_recommendations: string[];
}

interface Facts {
  pillar_1_globalization: {
    language_assessment_state?: "aligned" | "potential_gaps" | "needs_confirmation";
    language_gaps?: LanguageGap[];
    lcr_score?: number;
    lcr_tier?: string;
    lcr_available?: number;
    lcr_required?: number;
    lcr_covered?: number;
    required_languages?: string[];
    available_languages: string[];
    available_language_variants?: string[];
    crawler_ran?: boolean;
    hreflang_present: boolean;
    hreflang_x_default_present: boolean;
    geographic_presence?: string;
    mixed_language_issues?: { locale: string; page_url: string; language_hits: { language: string; marker_strings_found: string[] }[] }[];
    mixed_language_affected_locales_count?: number;
    estimated_monthly_traffic?: string;
    top_traffic_countries?: string[];
  };
  pillar_2_website_health: {
    performance_score_mobile?: number;
    performance_score_desktop?: number;
    seo_score_mobile?: number;
    accessibility_score_mobile?: number;
    site_health_score?: number;
    lcp_mobile?: string;
    cls_mobile?: string;
    broken_internal_urls?: number;
    missing_meta_descriptions?: number;
    pages_crawled?: number;
    psi_ran?: boolean;
    crawl_ran?: boolean;
    crawl_error?: string;
  };
  pillar_3_accessibility: {
    wcag_level_claimed?: string;
    has_accessibility_statement?: boolean;
    accessibility_statement_url?: string;
    has_cookie_banner?: boolean;
    primary_region?: string;
    applicable_regulations?: string[];
    wcag_issues?: string[];
  };
  pillar_4_online_reputation: {
    overall_sentiment?: string;
    trustpilot_url?: string;
    trustpilot_score?: number;
    trustpilot_reviews?: number;
    glassdoor_url?: string;
    glassdoor_score?: number;
    glassdoor_reviews?: number;
    indeed_url?: string;
    indeed_score?: number;
    indeed_reviews?: number;
    social_media?: Record<string, { url?: string; followers?: string; subscribers?: string; last_active?: string }>;
    trade_fair_presence?: unknown[];
    credibility_assets?: string[];
  };
  competitor_facts: Array<{
    company_name?: string;
    available_languages?: string[];
    lcr_score?: number;
    lcr_tier?: string;
    overall_sentiment?: string;
    linkedin_followers?: string;
    social_media_reach?: string;
    global_reach?: string;
    review_score?: number;
  }>;
  company_name: string;
  url: string;
}

interface ReportData {
  facts: Facts;
  ui_content: UiContent;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function scoreColor(score?: number) {
  if (score === undefined || score === null) return "text-gray-400";
  if (score >= 76) return "text-green-600";
  if (score >= 51) return "text-yellow-600";
  return "text-red-600";
}


function StarRating({ score, max = 5 }: { score?: number | string; max?: number }) {
  const num = typeof score === "string" ? parseFloat(score) : score;
  if (!num || isNaN(num)) return <span className="text-gray-400 text-sm">N/A</span>;
  const pct = Math.min((num / max) * 100, 100);
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 flex-1 bg-gray-100 rounded-full overflow-hidden">
        <div className="absolute inset-y-0 left-0 bg-green-500 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-semibold text-gray-700">{num.toFixed(1)}</span>
    </div>
  );
}

function PsiBar({ label, score }: { label: string; score?: number }) {
  const color = score === undefined ? "bg-gray-200" : score >= 76 ? "bg-green-500" : score >= 51 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{label}</span>
        <span className={`font-semibold ${scoreColor(score)}`}>{score ?? "N/A"}</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${score ?? 0}%` }} />
      </div>
    </div>
  );
}

function LcrDonut({ score, tier }: { score: number; tier: string }) {
  const r = 38;
  const circ = 2 * Math.PI * r;
  const dash = (score / 100) * circ;
  const tierColor = tier === "Full Coverage" ? "#16a34a" : tier === "Strong Coverage" ? "#65a30d" : tier === "Partial Coverage" ? "#ca8a04" : "#dc2626";
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} fill="none" stroke="#f3f4f6" strokeWidth="10" />
        <circle
          cx="50" cy="50" r={r} fill="none"
          stroke={tierColor} strokeWidth="10"
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
        />
        <text x="50" y="46" textAnchor="middle" fontSize="16" fontWeight="700" fill="#111827">{score}%</text>
        <text x="50" y="60" textAnchor="middle" fontSize="9" fill="#6b7280">LCR</text>
      </svg>
      <div className="flex items-center gap-1">
        <span className="text-xs font-medium text-gray-600">{tier}</span>
        <MetricPopover title="Language Coverage Rate" content="Required: languages needed to serve the company's key markets, derived from traffic data and geographic footprint. Available: languages where the full UX (navigation, catalog, checkout) is live. LCR = percentage of required languages that are currently live on the site." />
      </div>
    </div>
  );
}

function LanguageStateBadge({ state }: { state: string }) {
  const cfg: Record<string, { label: string; className: string }> = {
    aligned: { label: "Aligned", className: "bg-green-100 text-green-700 border-green-200" },
    potential_gaps: { label: "Potential Gaps", className: "bg-amber-100 text-amber-700 border-amber-200" },
    needs_confirmation: { label: "Needs Confirmation", className: "bg-gray-100 text-gray-600 border-gray-200" },
  };
  const { label, className } = cfg[state] ?? cfg.needs_confirmation;
  return (
    <span className={`px-3 py-1.5 rounded-full text-sm font-semibold border ${className}`}>{label}</span>
  );
}

function LanguageGapList({ gaps, state }: { gaps: LanguageGap[]; state: string }) {
  const grouped = gaps.reduce<Record<string, LanguageGap[]>>((acc, gap) => {
    (acc[gap.language] ??= []).push(gap);
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Language Coverage</p>
        <MetricPopover title="Language gap priority" content={
          <div className="flex flex-col gap-2">
            <div className="flex items-start gap-2">
              <span className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0 mt-1" />
              <span><span className="font-semibold text-gray-700">Critical</span> - strong evidence the company operates in this market. This language gap is a real localization risk.</span>
            </div>
            <div className="flex items-start gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400 flex-shrink-0 mt-1" />
              <span><span className="font-semibold text-gray-700">Suggested</span> - indirect signals only (traffic, country selector). Lower confidence but worth considering.</span>
            </div>
          </div>
        } />
        <LanguageStateBadge state={state} />
      </div>
      {gaps.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {Object.entries(grouped).map(([lang, entries]) => {
            const isStrong = entries[0].strength === "strong";
            const langName = LANG_NAMES[lang.toUpperCase()] ?? lang;
            return (
              <li key={lang} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  {isStrong
                    ? <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-red-500" />
                    : <span className="w-1.5 h-1.5 rounded-full flex-shrink-0 bg-amber-400" />
                  }
                  <span className="text-sm font-semibold text-gray-800">{langName}</span>
                  <span className="text-xs text-gray-400 font-mono">{lang}</span>
                </div>
                <ul className="flex flex-col gap-0.5 pl-3.5">
                  {entries.map((entry, i) => (
                    <li key={i} className="text-xs text-gray-500 leading-relaxed">{entry.reason}</li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-xs text-green-600">No language gaps identified.</p>
      )}
    </div>
  );
}

// ── Section components ────────────────────────────────────────────────────────

function SectionHeader({ id, title, subtitle }: { id: string; title: string; subtitle: string }) {
  return (
    <div id={id} className="flex items-start gap-3 pt-2">
      <div>
        <h2 className="text-xl font-bold text-gray-900">{title}</h2>
        <p className="text-sm text-green-700 font-medium mt-0.5">{subtitle}</p>
      </div>
    </div>
  );
}

function FindingsRecs({ findings, recommendations }: { findings: string[]; recommendations: string[] }) {
  return (
    <div className="flex flex-col gap-4 scroll-mt-20">
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Key Findings</h4>
        <ul className="flex flex-col gap-2">
          {findings.map((f, i) => (
            <li key={i} className="flex gap-2 text-sm text-gray-700">
              <span className="text-green-500 mt-0.5 flex-shrink-0">•</span>
              <span>{f}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Recommendations</h4>
        <ul className="flex flex-col gap-2">
          {recommendations.map((r, i) => (
            <li key={i} className="flex gap-2 text-sm text-gray-700">
              <span className="text-blue-400 mt-0.5 flex-shrink-0 font-bold">{i + 1}.</span>
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white rounded-xl border border-gray-200 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

function MetricPopover({ title, content }: { title: string; content: React.ReactNode }) {
  return (
    <Popover className="relative">
      <PopoverButton className="w-5 h-5 rounded-full bg-gray-200 text-gray-500 text-xs font-bold flex items-center justify-center hover:bg-gray-300 hover:scale-110 hover:text-gray-700 transition-all focus:outline-none cursor-pointer select-none">
        ?
      </PopoverButton>
      <PopoverPanel className="absolute z-50 bottom-full right-0 mb-2 bg-white border border-gray-200 rounded-xl shadow-lg p-4 text-left" style={{ width: '320px' }}>
        <p className="text-sm font-semibold text-gray-800 mb-1.5">{title}</p>
        <div className="text-xs text-gray-500 leading-relaxed">{content}</div>
      </PopoverPanel>
    </Popover>
  );
}

const LANG_NAMES: Record<string, string> = {
  AF: "Afrikaans", AR: "Arabic", AZ: "Azerbaijani", BE: "Belarusian", BG: "Bulgarian",
  BN: "Bengali", BS: "Bosnian", CA: "Catalan", CS: "Czech", CY: "Welsh",
  DA: "Danish", DE: "German", EL: "Greek", EN: "English", ES: "Spanish",
  ET: "Estonian", EU: "Basque", FA: "Persian", FI: "Finnish", FR: "French",
  GA: "Irish", GL: "Galician", GU: "Gujarati", HE: "Hebrew", HI: "Hindi",
  HR: "Croatian", HT: "Haitian Creole", HU: "Hungarian", HY: "Armenian",
  ID: "Indonesian", IS: "Icelandic", IT: "Italian", JA: "Japanese",
  KA: "Georgian", KK: "Kazakh", KM: "Khmer", KN: "Kannada", KO: "Korean",
  LT: "Lithuanian", LV: "Latvian", MK: "Macedonian", ML: "Malayalam",
  MN: "Mongolian", MR: "Marathi", MS: "Malay", MY: "Burmese", NE: "Nepali",
  NL: "Dutch", NO: "Norwegian", PA: "Punjabi", PL: "Polish", PT: "Portuguese",
  RO: "Romanian", RU: "Russian", SI: "Sinhala", SK: "Slovak", SL: "Slovenian",
  SQ: "Albanian", SR: "Serbian", SV: "Swedish", SW: "Swahili", TA: "Tamil",
  TE: "Telugu", TH: "Thai", TL: "Filipino", TR: "Turkish", UK: "Ukrainian",
  UR: "Urdu", UZ: "Uzbek", VI: "Vietnamese", ZH: "Chinese",
};

function CompetitorTable({ clientName, p1, competitors }: {
  clientName: string;
  p1: Facts["pillar_1_globalization"];
  competitors: Facts["competitor_facts"];
}) {
  const cols = [
    { name: clientName, langs: new Set((p1.available_languages ?? []).map(l => l.toUpperCase())), isClient: true },
    ...competitors.map(c => ({
      name: c.company_name ?? "-",
      langs: new Set((c.available_languages ?? []).map(l => l.toUpperCase())),
      isClient: false,
    })),
  ];

  const allLangs = Array.from(new Set(cols.flatMap(c => Array.from(c.langs)))).sort();

  return (
    <Card>
      <div className="overflow-auto max-h-[300px]">
        <table className="text-sm w-full">
          <thead className="sticky top-0 z-10">
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-5 py-3 font-semibold text-gray-600 whitespace-nowrap">Language</th>
              {cols.map((col, i) => (
                <th key={i} className={`px-3 py-3 text-xs font-semibold uppercase tracking-wider text-center whitespace-nowrap ${col.isClient ? "text-green-700" : "text-gray-500"}`}>
                  {col.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {allLangs.map(lang => (
              <tr key={lang} className="hover:bg-gray-50 transition">
                <td className="px-5 py-3 text-gray-700 text-xs whitespace-nowrap">
                  {LANG_NAMES[lang] && <span className="text-sm text-gray-700 font-normal normal-case">{LANG_NAMES[lang]}</span>}
                  <span className="ml-1.5 text-[10px] uppercase tracking-wider text-gray-400">{lang}</span>
                </td>
                {cols.map((col, i) => (
                  <td key={i} className={`px-3 py-3 text-center${col.isClient ? " bg-green-50" : ""}`}>
                    {col.langs.has(lang) ? (
                      <span className={col.isClient ? "text-green-600 font-bold" : "text-gray-400"}>✓</span>
                    ) : (
                      <span className="text-gray-200">–</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 z-10">
            <tr className="border-t-2 border-gray-200 bg-gray-50">
              <td className="px-5 py-3 text-xs font-semibold text-gray-600">Total</td>
              {cols.map((col, i) => (
                <td key={i} className={`px-3 py-3 text-center text-xs font-bold${col.isClient ? " text-green-700 bg-green-50" : " text-gray-600"}`}>
                  {col.langs.size}
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function ResultPage() {
  const params = useParams();
  const job_id = params.job_id as string;

  const [meta, setMeta] = useState<AuditMeta | null>(null);
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [copied, setCopied] = useState(false);
  const [downloading, setDownloading] = useState(false);

  async function handleDownloadPdf() {
    setDownloading(true);
    try {
      // parse backend pdf bytes response and trigger download
      const bytes = await getAuditPdf(job_id);
      const blob = new Blob([bytes.buffer as ArrayBuffer], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${meta?.company_name ?? "report"}-preaudit.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch {
      alert("Failed to generate PDF. Please try again.");
    } finally {
      setDownloading(false);
    }
  }

  useEffect(() => {
    Promise.all([
      getAuditDetails(job_id),
      getAuditResult(job_id),
    ])
      .then(([metaData, resultData]) => {
        setMeta({ company_name: metaData.company_name, url: metaData.url, created_at: metaData.created_at });
        setData(resultData as ReportData);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "Failed to load result. Is the backend running?");
        setLoading(false);
      });
  }, [job_id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-green-700" />
          <p className="text-gray-600">Loading report...</p>
        </div>
      </div>
    );
  }

  if (error || !data || !meta) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center px-6">
        <div className="flex flex-col items-center gap-4 text-center max-w-md">
          <h1 className="text-2xl font-bold text-red-600">Error</h1>
          <p className="text-gray-700">{error ?? "No data available."}</p>
          <Link href="/audits" className="text-green-700 font-semibold hover:text-green-800">← All Audits</Link>
        </div>
      </div>
    );
  }

  const { facts, ui_content } = data;
  const p1 = facts.pillar_1_globalization;
  const p2 = facts.pillar_2_website_health;
  const p2DataWarning =
    p2.psi_ran === false && p2.crawl_ran === false
      ? "Performance and crawl data could not be collected. Pillar 2 findings are based on limited information only."
      : p2.crawl_ran === false && p2.crawl_error?.startsWith("Bot-blocked")
      ? "Site health data unavailable - bot protection prevented the crawler from accessing this site. PSI scores above are unaffected."
      : p2.crawl_ran === false && p2.crawl_error
      ? `Crawl data unavailable: ${p2.crawl_error}`
      : p2.psi_ran === false
      ? "PageSpeed data could not be collected for this site."
      : p2.crawl_ran !== false && p2.pages_crawled === 1
      ? "Crawl limited to 1 page - metrics reflect the homepage only, not the full site."
      : null;
  const p3 = facts.pillar_3_accessibility;
  const p4 = facts.pillar_4_online_reputation;

  const navAnchors = [
    { id: "summary", label: "Summary" },
    { id: "pillar1", label: "Globalization" },
    { id: "pillar2", label: "Website Health" },
    { id: "pillar3", label: "Accessibility" },
    { id: "pillar4", label: "Reputation" },
    { id: "competitors", label: "Competitors" },
  ];

  return (
    <div className="min-h-screen bg-slate-50">

      {/* Sticky top bar */}
      <div className="sticky top-0 z-30 bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/audits" className="text-green-700 hover:text-green-800 text-sm font-semibold whitespace-nowrap">
              ← All Audits
            </Link>
            <div className="hidden md:block h-4 w-px bg-gray-200" />
            <div className="min-w-0">
              <span className="font-bold text-gray-900 truncate">{meta.company_name}</span>
              <a href={meta.url} target="_blank" rel="noopener noreferrer" className="text-gray-400 text-sm ml-2 truncate hidden lg:inline hover:text-green-700 hover:underline">{meta.url}</a>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-1">
            {navAnchors.map((a) => (
              <a
                key={a.id}
                href={`#${a.id}`}
                className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-green-700 hover:bg-green-50 rounded-lg transition-colors"
              >
                {a.label}
              </a>
            ))}
          </nav>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col gap-10">

        {/* Header */}
        <div className="flex items-start justify-between gap-6">
          <div>
            <p className="text-green-700 text-xs font-mono tracking-widest uppercase mb-3">AI Generated Report</p>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight mb-2">{meta.company_name}</h1>
            <a href={meta.url} target="_blank" rel="noopener noreferrer" className="text-gray-500 text-sm hover:text-green-700 hover:underline transition-colors">{meta.url}</a>
            {meta.created_at && (
              <p className="text-gray-400 text-xs mt-3">
                Generated {new Date(meta.created_at).toLocaleDateString("en-US", {
                  month: "long", day: "numeric", year: "numeric",
                })}
              </p>
            )}
          </div>
          <button
            onClick={handleDownloadPdf}
            disabled={downloading}
            className={`flex items-center gap-1.5 text-sm font-semibold text-green-700 hover:text-green-900 cursor-pointer transition-colors whitespace-nowrap mt-1 ${downloading ? "animate-pulse" : ""}`}
          >
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 1v8M4 6l3 3 3-3M1 12h12" />
            </svg>
            PDF
          </button>
        </div>

        {/* Executive Summary */}
        <section id="summary" className="scroll-mt-20">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Executive Summary</h2>
          <Card className="p-6">
            <ul className="flex flex-col gap-3">
              {(ui_content?.executive_summary ?? []).map((bullet, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <span className="mt-1 flex-shrink-0 w-5 h-5 rounded-full bg-green-100 text-green-700 text-xs font-bold flex items-center justify-center">{i + 1}</span>
                  <span className="text-gray-800">{bullet}</span>
                </li>
              ))}
            </ul>
          </Card>
        </section>

        {/* Top Recommendations */}
        {ui_content?.top_recommendations?.length > 0 && (
          <Card className="p-6">
            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">Top Cross-Pillar Recommendations</h3>
            <ol className="flex flex-col gap-3">
              {ui_content.top_recommendations.map((r, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-50 text-blue-600 text-xs font-bold flex items-center justify-center">{i + 1}</span>
                  <span className="text-gray-700 text-sm">{r}</span>
                </li>
              ))}
            </ol>
          </Card>
        )}

        {/* ── Pillar 1: Globalization ─────────────────────────────────────── */}
        <section id="pillar1" className="flex flex-col gap-4 scroll-mt-20">
          <SectionHeader id="pillar1-hdr" title="Pillar 1 - Globalization" subtitle={ui_content?.pillar_1?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            {/* Left: stats */}
            <Card className="p-5 flex flex-col gap-5">
              {p1.language_gaps !== undefined ? (
                <LanguageGapList gaps={p1.language_gaps} state={p1.language_assessment_state ?? "needs_confirmation"} />
              ) : (
                <div className="flex items-center justify-between">
                  <LcrDonut score={p1.lcr_score ?? 0} tier={p1.lcr_tier ?? ""} />
                  <div className="flex flex-col gap-1 text-right">
                    <span className="text-xs text-gray-500">Languages live on site</span>
                    <span className="text-2xl font-bold text-gray-900">{p1.lcr_available ?? 0}</span>
                    <span className="text-xs text-gray-400">covering {p1.lcr_covered ?? 0} of {p1.lcr_required ?? 0} required</span>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs text-gray-500">Hreflang</p>
                    <MetricPopover title="Hreflang tags" content="HTML tags that tell search engines which language and region version of a page to serve and should be in the page's header. Missing/incorrectly placed hreflang tags hurt international SEO ranking for multilingual sites. N/A means the result is inconclusive." />
                  </div>
                  {p1.crawler_ran === false
                    ? <p className="font-semibold text-gray-400">N/A</p>
                    : <p className={`font-semibold ${p1.hreflang_present ? "text-green-600" : "text-red-600"}`}>{p1.hreflang_present ? "Present" : "Missing"}</p>
                  }
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs text-gray-500">x-default</p>
                    <MetricPopover title="x-default Hreflang" content="A special hreflang tag that designates the fallback page for users whose language or region doesn't match any of the targeted locales. Without it, search engines have no default to fall back on. N/A means the result is inconclusive." />
                  </div>
                  {p1.crawler_ran === false
                    ? <p className="font-semibold text-gray-400">N/A</p>
                    : <p className={`font-semibold ${p1.hreflang_x_default_present ? "text-green-600" : "text-red-600"}`}>{p1.hreflang_x_default_present ? "Present" : "Missing"}</p>
                  }
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs text-gray-500">Mixed language issues</p>
                    <MetricPopover
                      title="Mixed language issues"
                      content={(() => {
                        const issues = p1.mixed_language_issues ?? [];
                        const shown = issues.slice(0, 3);
                        const extra = issues.length - 3;
                        return (
                          <div className="flex flex-col gap-2">
                            <p>Pages where the visible text doesn't match the declared locale - confuses both users and search engines.</p>
                            {issues.length > 0 && (
                              <div>
                                <p className="font-medium text-gray-700 mb-1">Found in this audit:</p>
                                <ul className="flex flex-col gap-1">
                                  {shown.map((issue, i) => {
                                    const hit = issue.language_hits[0];
                                    const examples = hit?.marker_strings_found?.slice(0, 2).join('", "');
                                    return (
                                      <li key={i} className="flex gap-1.5">
                                        <span className="text-red-400 flex-shrink-0">•</span>
                                        <span><span className="font-medium">{issue.locale}</span>{hit && <> — {hit.language} text: &ldquo;{examples}&rdquo;</>}</span>
                                      </li>
                                    );
                                  })}
                                  {extra > 0 && <li className="text-gray-400 italic">and {extra} more…</li>}
                                </ul>
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    />
                  </div>
                  <p className={`font-semibold ${((p1.mixed_language_affected_locales_count != null ? p1.mixed_language_affected_locales_count : (p1.mixed_language_issues?.length ?? 0)) > 0) ? "text-red-600" : "text-green-600"}`}>
                    {p1.mixed_language_affected_locales_count != null ? p1.mixed_language_affected_locales_count : (p1.mixed_language_issues?.length ?? 0)} locale(s)
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Organic Monthly Traffic</p>
                  <p className="font-semibold text-gray-700">{p1.estimated_monthly_traffic ?? "N/A"}</p>
                </div>
              </div>

              {p1.available_languages?.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-2">Available languages</p>
                  <div className="flex flex-wrap gap-1">
                    {p1.available_languages.map((lang) => (
                      <span key={lang} className="px-2 py-0.5 bg-green-50 text-green-700 text-xs font-medium rounded-md">
                        {LANG_NAMES[lang.toUpperCase()] ?? lang}
                      </span>
                    ))}
                  </div>
                  {(p1.available_language_variants?.length ?? 0) > 0 && (
                    <div className="mt-2">
                      <p className="text-xs text-gray-400 mb-1">Regional variants</p>
                      <div className="flex flex-wrap gap-1">
                        {p1.available_language_variants?.map((v) => (
                          <span key={v} className="px-2 py-0.5 bg-gray-50 text-gray-500 text-xs font-medium rounded-md">{v}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* Right: findings + recs */}
            <Card className="p-5">
              <FindingsRecs
                findings={ui_content?.pillar_1?.findings ?? []}
                recommendations={ui_content?.pillar_1?.recommendations ?? []}
              />
            </Card>
          </div>
        </section>

        {/* ── Pillar 2: Website Health ────────────────────────────────────── */}
        <section id="pillar2" className="flex flex-col gap-4 scroll-mt-20">
          <SectionHeader id="pillar2-hdr" title="Pillar 2 - Website Health" subtitle={ui_content?.pillar_2?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            <Card className="p-5 flex flex-col gap-5">
              {p2.psi_ran ? (
                <div className="flex flex-col gap-3">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">PageSpeed Insights</p>
                  <PsiBar label="Performance (Mobile)" score={p2.performance_score_mobile} />
                  <PsiBar label="Performance (Desktop)" score={p2.performance_score_desktop} />
                  <PsiBar label="SEO Score (Mobile)" score={p2.seo_score_mobile} />
                  <PsiBar label="Accessibility Score (Mobile)" score={p2.accessibility_score_mobile} />
                </div>
              ) : (
                <p className="text-sm text-gray-400 italic">PageSpeed data not available.</p>
              )}

              {p2DataWarning && (
                <div className="flex items-start gap-2 rounded-lg bg-yellow-50 border border-yellow-200 px-3 py-2 text-xs text-yellow-800 mb-3">
                  <span className="mt-0.5">⚠</span>
                  <span>{p2DataWarning}</span>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 text-sm">
                {p2.crawl_ran !== false && p2.site_health_score !== undefined && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-gray-500">Site health score</p>
                      <MetricPopover title="Site health score" content="A composite score (0–100) measuring technical SEO quality - crawlability, broken links, missing meta tags, redirect chains, and more. Scores above 75 are healthy; below 50 indicate issues that hurt search visibility." />
                    </div>
                    <p className={`font-bold text-lg ${scoreColor(p2.site_health_score)}`}>{p2.site_health_score}/100</p>
                  </div>
                )}
                {p2.lcp_mobile && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-xs text-gray-500"><abbr title="Largest Contentful Paint">LCP</abbr> Mobile</p>
                      <MetricPopover title="LCP Mobile" content="Largest Contentful Paint - the time it takes for the main content of a page to load on mobile. Google uses this as a Core Web Vital. Under 2.5s is good; over 4s is poor and hurts rankings." />
                    </div>
                    <p className="font-semibold text-gray-700">{p2.lcp_mobile}</p>
                  </div>
                )}
                {p2.crawl_ran !== false && p2.broken_internal_urls !== undefined && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Broken links</p>
                    <p className={`font-semibold ${p2.broken_internal_urls > 0 ? "text-red-600" : "text-green-600"}`}>
                      {p2.broken_internal_urls}
                    </p>
                  </div>
                )}
                {p2.crawl_ran !== false && p2.missing_meta_descriptions !== undefined && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Missing meta desc.</p>
                    <p className={`font-semibold ${p2.missing_meta_descriptions > 0 ? "text-yellow-600" : "text-green-600"}`}>
                      {p2.missing_meta_descriptions}
                    </p>
                  </div>
                )}
              </div>
            </Card>

            <Card className="p-5">
              <FindingsRecs
                findings={ui_content?.pillar_2?.findings ?? []}
                recommendations={ui_content?.pillar_2?.recommendations ?? []}
              />
            </Card>
          </div>
        </section>

        {/* ── Pillar 3: Accessibility ─────────────────────────────────────── */}
        <section id="pillar3" className="flex flex-col gap-4 scroll-mt-20">
          <SectionHeader id="pillar3-hdr" title="Pillar 3 - Accessibility & Compliance" subtitle={ui_content?.pillar_3?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            <Card className="p-5 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1"><abbr title="Web Content Accessibility Guidelines">WCAG</abbr> level</p>
                  {p3.wcag_level_claimed && p3.wcag_level_claimed !== "undeclared"
                    ? <p className="font-semibold text-gray-700">{p3.wcag_level_claimed}</p>
                    : p3.accessibility_statement_url
                    ? <a href={p3.accessibility_statement_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-amber-600 hover:underline text-xs">Undeclared - verify in statement</a>
                    : <p className="font-semibold text-gray-400">Undeclared</p>
                  }
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Accessibility statement</p>
                  {p3.has_accessibility_statement && p3.accessibility_statement_url
                    ? <a href={p3.accessibility_statement_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-green-600 hover:underline">Yes</a>
                    : <p className={`font-semibold ${p3.has_accessibility_statement ? "text-green-600" : "text-red-600"}`}>{p3.has_accessibility_statement ? "Yes" : "No"}</p>
                  }
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Cookie consent</p>
                  <p className={`font-semibold ${p3.has_cookie_banner ? "text-green-600" : "text-gray-400"}`}>
                    {p3.has_cookie_banner ? "Yes" : "Undetected"}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Primary region</p>
                  <p className="font-semibold text-gray-700">{p3.primary_region ?? "N/A"}</p>
                </div>
              </div>

              {(p3.applicable_regulations?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-2">Applicable regulations</p>
                  <div className="flex flex-wrap gap-1">
                    {p3.applicable_regulations!.map((r) => (
                      <span key={r} className="px-2 py-0.5 bg-blue-50 text-blue-700 text-xs font-medium rounded-md">{r}</span>
                    ))}
                  </div>
                </div>
              )}

              {(p3.wcag_issues?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-2">Issues identified</p>
                  <ul className="flex flex-col gap-1">
                    {p3.wcag_issues!.map((issue, i) => (
                      <li key={i} className="text-xs text-red-700 flex gap-1.5">
                        <span className="text-red-400 mt-0.5">!</span>
                        <span>{issue}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>

            <Card className="p-5">
              <FindingsRecs
                findings={ui_content?.pillar_3?.findings ?? []}
                recommendations={ui_content?.pillar_3?.recommendations ?? []}
              />
            </Card>
          </div>
        </section>

        {/* ── Pillar 4: Online Reputation ─────────────────────────────────── */}
        <section id="pillar4" className="flex flex-col gap-4 scroll-mt-20">
          <SectionHeader id="pillar4-hdr" title="Pillar 4 - Online Reputation" subtitle={ui_content?.pillar_4?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            <Card className="p-5 flex flex-col gap-5">
              <div className="flex flex-col gap-3">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Review Ratings</p>
                {(p4.trustpilot_score != null || p4.trustpilot_url) && (
                  <div className="flex items-center gap-3">
                    {p4.trustpilot_url ? (
                      <a href={p4.trustpilot_url} target="_blank" rel="noopener noreferrer" className="w-24 text-xs text-blue-600 hover:text-blue-800 underline underline-offset-2">Trustpilot</a>
                    ) : (
                      <span className="w-24 text-xs text-gray-600">Trustpilot</span>
                    )}
                    <div className="flex-1"><StarRating score={p4.trustpilot_score} /></div>
                    <span className="text-xs text-gray-400">{p4.trustpilot_reviews != null ? `${p4.trustpilot_reviews} reviews` : ""}</span>
                  </div>
                )}
                {(p4.glassdoor_score != null || p4.glassdoor_url) && (
                  <div className="flex items-center gap-3">
                    {p4.glassdoor_url ? (
                      <a href={p4.glassdoor_url} target="_blank" rel="noopener noreferrer" className="w-24 text-xs text-blue-600 hover:text-blue-800 underline underline-offset-2">Glassdoor</a>
                    ) : (
                      <span className="w-24 text-xs text-gray-600">Glassdoor</span>
                    )}
                    <div className="flex-1"><StarRating score={p4.glassdoor_score} /></div>
                    <span className="text-xs text-gray-400">{p4.glassdoor_reviews != null ? `${p4.glassdoor_reviews} reviews` : ""}</span>
                  </div>
                )}
                {(p4.indeed_score != null || p4.indeed_url) && (
                  <div className="flex items-center gap-3">
                    {p4.indeed_url ? (
                      <a href={p4.indeed_url} target="_blank" rel="noopener noreferrer" className="w-24 text-xs text-blue-600 hover:text-blue-800 underline underline-offset-2">Indeed</a>
                    ) : (
                      <span className="w-24 text-xs text-gray-600">Indeed</span>
                    )}
                    <div className="flex-1"><StarRating score={p4.indeed_score} /></div>
                    <span className="text-xs text-gray-400">{p4.indeed_reviews != null ? `${p4.indeed_reviews} reviews` : ""}</span>
                  </div>
                )}
              </div>

              {Object.keys(p4.social_media ?? {}).length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Social Media</p>
                  <div className="flex flex-col gap-1.5">
                    {Object.entries(p4.social_media!).map(([platform, d]) => {
                      if (!d?.url) return null;
                      const rawCount = d.followers ?? d.subscribers;
                      const hasCount = rawCount && rawCount !== "N/A";
                      const cleaned = hasCount && typeof rawCount === "string" ? rawCount.replace(/,/g, "") : "";
                      const num = cleaned ? parseInt(cleaned, 10) : NaN;
                      const isPlainNumber = !isNaN(num) && String(num) === cleaned;
                      const display = isPlainNumber ? `~${num.toLocaleString()}` : `~${rawCount}`;
                      return (
                        <div key={platform} className="flex items-center justify-between text-sm">
                          <a href={d.url} target="_blank" rel="noopener noreferrer" className="capitalize text-gray-600 hover:text-green-700 underline underline-offset-2">
                            {platform}
                          </a>
                          {hasCount ? (
                            <span className="font-semibold text-gray-800">{display}</span>
                          ) : (
                            <a href={d.url} target="_blank" rel="noopener noreferrer" className="text-xs text-gray-400 hover:text-green-700 hover:underline">View page →</a>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </Card>

            <Card className="p-5">
              <FindingsRecs
                findings={ui_content?.pillar_4?.findings ?? []}
                recommendations={ui_content?.pillar_4?.recommendations ?? []}
              />
            </Card>
          </div>
        </section>

        {/* ── Competitive Landscape ───────────────────────────────────────── */}
        <section id="competitors" className="flex flex-col gap-4 scroll-mt-20">
          <SectionHeader id="competitors-hdr" title="Competitive Landscape" subtitle="How the client compares to the competitive set" />

          {facts.competitor_facts?.length > 0 && (
            <CompetitorTable
              clientName={facts.company_name}
              p1={p1}
              competitors={facts.competitor_facts}
            />
          )}

          {ui_content?.competitive_landscape && (
            <Card className="p-5">
              <p className="text-gray-700 text-sm leading-relaxed mb-4">{ui_content.competitive_landscape.summary}</p>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <h4 className="text-xs font-semibold text-green-600 uppercase tracking-wider mb-2">Advantages</h4>
                  <ul className="flex flex-col gap-1.5">
                    {ui_content.competitive_landscape.client_advantages.map((a, i) => (
                      <li key={i} className="flex gap-2 text-sm text-gray-700">
                        <span className="text-green-500 flex-shrink-0">+</span>
                        <span>{a}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h4 className="text-xs font-semibold text-red-500 uppercase tracking-wider mb-2">Gaps</h4>
                  <ul className="flex flex-col gap-1.5">
                    {ui_content.competitive_landscape.client_gaps.map((g, i) => (
                      <li key={i} className="flex gap-2 text-sm text-gray-700">
                        <span className="text-red-400 flex-shrink-0">-</span>
                        <span>{g}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Card>
          )}
        </section>

        {/* Raw JSON */}
        <div className="border-t border-gray-200 pt-6">
          <button
            onClick={() => setShowRaw((v) => !v)}
            className="text-sm text-gray-400 hover:text-gray-600 font-medium cursor-pointer"
          >
            {showRaw ? "Hide" : "View"} raw JSON
          </button>
          {showRaw && (
            <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-600">Raw Report JSON</span>
                <button
                  onClick={() => { navigator.clipboard.writeText(JSON.stringify(data, null, 2)); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
                  className={`text-xs font-medium transition-colors cursor-pointer ${copied ? 'text-gray-400' : 'text-green-700 hover:text-green-800'}`}
                >
                  {copied ? 'Copied ✓' : 'Copy'}
                </button>
              </div>
              <pre className="p-5 text-xs text-gray-800 overflow-auto max-h-[70vh] leading-relaxed">
                {JSON.stringify(data, null, 2)}
              </pre>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
