"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

// ── Types ────────────────────────────────────────────────────────────────────

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
    lcr_score: number;
    lcr_tier: string;
    lcr_available: number;
    lcr_required: number;
    available_languages: string[];
    required_languages: string[];
    hreflang_present: boolean;
    hreflang_x_default_present: boolean;
    geographic_presence?: string;
    mixed_language_issues?: unknown[];
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
  };
  pillar_3_accessibility: {
    wcag_level_claimed?: string;
    has_accessibility_statement?: boolean;
    has_cookie_banner?: boolean;
    primary_region?: string;
    applicable_regulations?: string[];
    wcag_issues?: string[];
  };
  pillar_4_online_reputation: {
    overall_sentiment?: string;
    trustpilot_score?: number;
    trustpilot_reviews?: number;
    glassdoor_score?: number;
    glassdoor_reviews?: number;
    indeed_score?: number;
    indeed_reviews?: number;
    google_reviews_score?: number;
    google_reviews_count?: number;
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

function sentimentColor(s?: string) {
  if (!s) return "bg-gray-100 text-gray-600";
  const l = s.toLowerCase();
  if (l === "positive") return "bg-green-100 text-green-700";
  if (l === "negative") return "bg-red-100 text-red-700";
  return "bg-yellow-100 text-yellow-700";
}

function scoreColor(score?: number) {
  if (score === undefined || score === null) return "text-gray-400";
  if (score >= 70) return "text-green-600";
  if (score >= 50) return "text-yellow-600";
  return "text-red-600";
}

function StarRating({ score, max = 5 }: { score?: number | string; max?: number }) {
  const num = typeof score === "string" ? parseFloat(score) : score;
  if (!num || isNaN(num)) return <span className="text-gray-400 text-sm">N/A</span>;
  const pct = Math.min((num / max) * 100, 100);
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-2 flex-1 bg-gray-100 rounded-full overflow-hidden">
        <div className="absolute inset-y-0 left-0 bg-orange-400 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-semibold text-gray-700">{num.toFixed(1)}</span>
    </div>
  );
}

function PsiBar({ label, score }: { label: string; score?: number }) {
  const color = score === undefined ? "bg-gray-200" : score >= 70 ? "bg-green-500" : score >= 50 ? "bg-yellow-500" : "bg-red-500";
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
      <span className="text-xs font-medium text-gray-600">{tier}</span>
    </div>
  );
}

// ── Section components ────────────────────────────────────────────────────────

function SectionHeader({ id, title, subtitle }: { id: string; title: string; subtitle: string }) {
  return (
    <div id={id} className="flex items-start gap-3 pt-2">
      <div>
        <h2 className="text-xl font-bold text-gray-900">{title}</h2>
        <p className="text-sm text-orange-600 font-medium mt-0.5">{subtitle}</p>
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
              <span className="text-orange-400 mt-0.5 flex-shrink-0">•</span>
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

// ── Main page ────────────────────────────────────────────────────────────────

export default function ResultPage() {
  const params = useParams();
  const job_id = params.job_id as string;

  const [meta, setMeta] = useState<AuditMeta | null>(null);
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL;
    Promise.all([
      fetch(`${base}/audits/${job_id}`).then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`);
        return r.json();
      }),
      fetch(`${base}/audits/${job_id}/result`).then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Error ${r.status}`);
        return r.json();
      }),
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
      <div className="min-h-screen bg-gradient-to-b from-white to-orange-50 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
          <p className="text-gray-600">Loading report...</p>
        </div>
      </div>
    );
  }

  if (error || !data || !meta) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-white to-orange-50 flex items-center justify-center px-6">
        <div className="flex flex-col items-center gap-4 text-center max-w-md">
          <h1 className="text-2xl font-bold text-red-600">Error</h1>
          <p className="text-gray-700">{error ?? "No data available."}</p>
          <Link href="/audits" className="text-orange-600 font-semibold hover:text-orange-700">← All Audits</Link>
        </div>
      </div>
    );
  }

  const { facts, ui_content } = data;
  const p1 = facts.pillar_1_globalization;
  const p2 = facts.pillar_2_website_health;
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
    <div className="min-h-screen bg-gradient-to-b from-white to-orange-50">

      {/* Sticky top bar */}
      <div className="sticky top-0 z-30 bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/audits" className="text-orange-600 hover:text-orange-700 text-sm font-semibold whitespace-nowrap">
              ← All Audits
            </Link>
            <div className="hidden md:block h-4 w-px bg-gray-200" />
            <div className="min-w-0">
              <span className="font-bold text-gray-900 truncate">{meta.company_name}</span>
              <span className="text-gray-400 text-sm ml-2 truncate hidden lg:inline">{meta.url}</span>
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-1">
            {navAnchors.map((a) => (
              <a
                key={a.id}
                href={`#${a.id}`}
                className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-orange-600 hover:bg-orange-50 rounded-lg transition-colors"
              >
                {a.label}
              </a>
            ))}
          </nav>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col gap-10">

        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{meta.company_name}</h1>
          <p className="text-gray-500 mt-1">{meta.url}</p>
          {meta.created_at && (
            <p className="text-gray-400 text-xs mt-1">
              Generated {new Date(meta.created_at).toLocaleDateString("en-US", {
                month: "long", day: "numeric", year: "numeric",
              })}
            </p>
          )}
        </div>

        {/* Executive Summary */}
        <section id="summary" className="scroll-mt-20">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Executive Summary</h2>
          <Card className="p-6">
            <ul className="flex flex-col gap-3">
              {(ui_content?.executive_summary ?? []).map((bullet, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <span className="mt-1 flex-shrink-0 w-5 h-5 rounded-full bg-orange-100 text-orange-600 text-xs font-bold flex items-center justify-center">{i + 1}</span>
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
          <SectionHeader id="pillar1-hdr" title="Pillar 1 — Globalization" subtitle={ui_content?.pillar_1?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            {/* Left: stats */}
            <Card className="p-5 flex flex-col gap-5">
              <div className="flex items-center justify-between">
                <LcrDonut score={p1.lcr_score ?? 0} tier={p1.lcr_tier ?? ""} />
                <div className="flex flex-col gap-1 text-right">
                  <span className="text-xs text-gray-500">Languages available</span>
                  <span className="text-2xl font-bold text-gray-900">{p1.lcr_available ?? 0}</span>
                  <span className="text-xs text-gray-400">of {p1.lcr_required ?? 0} required</span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Hreflang</p>
                  <p className={`font-semibold ${p1.hreflang_present ? "text-green-600" : "text-red-600"}`}>
                    {p1.hreflang_present ? "Present" : "Missing"}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">x-default</p>
                  <p className={`font-semibold ${p1.hreflang_x_default_present ? "text-green-600" : "text-red-600"}`}>
                    {p1.hreflang_x_default_present ? "Present" : "Missing"}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Mixed language issues</p>
                  <p className={`font-semibold ${(p1.mixed_language_issues?.length ?? 0) > 0 ? "text-red-600" : "text-green-600"}`}>
                    {p1.mixed_language_issues?.length ?? 0} locale(s)
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Monthly traffic</p>
                  <p className="font-semibold text-gray-700">{p1.estimated_monthly_traffic ?? "N/A"}</p>
                </div>
              </div>

              {p1.available_languages?.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-2">Available languages</p>
                  <div className="flex flex-wrap gap-1">
                    {p1.available_languages.map((lang) => (
                      <span key={lang} className="px-2 py-0.5 bg-orange-50 text-orange-700 text-xs font-medium rounded-md">{lang}</span>
                    ))}
                  </div>
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
          <SectionHeader id="pillar2-hdr" title="Pillar 2 — Website Health" subtitle={ui_content?.pillar_2?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            {/* Left: PSI scores + crawl stats */}
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

              <div className="grid grid-cols-2 gap-3 text-sm">
                {p2.site_health_score !== undefined && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Site health score</p>
                    <p className={`font-bold text-lg ${scoreColor(p2.site_health_score)}`}>{p2.site_health_score}/100</p>
                  </div>
                )}
                {p2.lcp_mobile && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">LCP Mobile</p>
                    <p className="font-semibold text-gray-700">{p2.lcp_mobile}</p>
                  </div>
                )}
                {p2.broken_internal_urls !== undefined && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Broken links</p>
                    <p className={`font-semibold ${p2.broken_internal_urls > 0 ? "text-red-600" : "text-green-600"}`}>
                      {p2.broken_internal_urls}
                    </p>
                  </div>
                )}
                {p2.missing_meta_descriptions !== undefined && (
                  <div className="bg-gray-50 rounded-lg p-3">
                    <p className="text-xs text-gray-500 mb-1">Missing meta desc.</p>
                    <p className={`font-semibold ${p2.missing_meta_descriptions > 0 ? "text-yellow-600" : "text-green-600"}`}>
                      {p2.missing_meta_descriptions}
                    </p>
                  </div>
                )}
              </div>
            </Card>

            {/* Right */}
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
          <SectionHeader id="pillar3-hdr" title="Pillar 3 — Accessibility & Compliance" subtitle={ui_content?.pillar_3?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            {/* Left */}
            <Card className="p-5 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">WCAG level</p>
                  <p className="font-semibold text-gray-700">{p3.wcag_level_claimed ?? "Undeclared"}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Accessibility statement</p>
                  <p className={`font-semibold ${p3.has_accessibility_statement ? "text-green-600" : "text-red-600"}`}>
                    {p3.has_accessibility_statement ? "Yes" : "No"}
                  </p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Cookie consent</p>
                  <p className={`font-semibold ${p3.has_cookie_banner ? "text-green-600" : "text-red-600"}`}>
                    {p3.has_cookie_banner ? "Yes" : "No"}
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

            {/* Right */}
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
          <SectionHeader id="pillar4-hdr" title="Pillar 4 — Online Reputation" subtitle={ui_content?.pillar_4?.headline ?? ""} />
          <div className="grid md:grid-cols-2 gap-4">

            {/* Left */}
            <Card className="p-5 flex flex-col gap-5">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500 mb-1">Overall sentiment</p>
                  <span className={`px-3 py-1 rounded-full text-sm font-semibold capitalize ${sentimentColor(p4.overall_sentiment)}`}>
                    {p4.overall_sentiment ?? "N/A"}
                  </span>
                </div>
              </div>

              <div className="flex flex-col gap-3">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Review Ratings</p>
                {p4.trustpilot_score != null && (
                  <div className="flex items-center gap-3">
                    <span className="w-24 text-xs text-gray-600">Trustpilot</span>
                    <div className="flex-1"><StarRating score={p4.trustpilot_score} /></div>
                    <span className="text-xs text-gray-400">{p4.trustpilot_reviews} reviews</span>
                  </div>
                )}
                {p4.google_reviews_score != null && (
                  <div className="flex items-center gap-3">
                    <span className="w-24 text-xs text-gray-600">Google</span>
                    <div className="flex-1"><StarRating score={p4.google_reviews_score} /></div>
                    <span className="text-xs text-gray-400">{p4.google_reviews_count} reviews</span>
                  </div>
                )}
                {p4.glassdoor_score != null && (
                  <div className="flex items-center gap-3">
                    <span className="w-24 text-xs text-gray-600">Glassdoor</span>
                    <div className="flex-1"><StarRating score={p4.glassdoor_score} /></div>
                    <span className="text-xs text-gray-400">{p4.glassdoor_reviews} reviews</span>
                  </div>
                )}
                {p4.indeed_score != null && (
                  <div className="flex items-center gap-3">
                    <span className="w-24 text-xs text-gray-600">Indeed</span>
                    <div className="flex-1"><StarRating score={p4.indeed_score} /></div>
                    <span className="text-xs text-gray-400">{p4.indeed_reviews} reviews</span>
                  </div>
                )}
              </div>

              {/* Social media */}
              {Object.keys(p4.social_media ?? {}).length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Social Media</p>
                  <div className="flex flex-col gap-1.5">
                    {Object.entries(p4.social_media!).map(([platform, d]) => {
                      if (!d?.url) return null;
                      const rawCount = d.followers ?? d.subscribers;
                      if (!rawCount || rawCount === "N/A") return null;
                      const num = typeof rawCount === "string" ? parseInt(rawCount.replace(/,/g, ""), 10) : rawCount;
                      const display = !isNaN(num) ? num.toLocaleString() : rawCount;
                      return (
                        <div key={platform} className="flex items-center justify-between text-sm">
                          <span className="capitalize text-gray-600">{platform}</span>
                          <span className="font-semibold text-gray-800">{display}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </Card>

            {/* Right */}
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
            className="text-sm text-gray-400 hover:text-gray-600 font-medium"
          >
            {showRaw ? "Hide" : "View"} raw JSON
          </button>
          {showRaw && (
            <div className="mt-4 bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-600">Raw Report JSON</span>
                <button
                  onClick={() => navigator.clipboard.writeText(JSON.stringify(data, null, 2))}
                  className="text-xs text-orange-600 hover:text-orange-700 font-medium"
                >
                  Copy
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
