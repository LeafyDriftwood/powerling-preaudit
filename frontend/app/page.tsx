"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';
import { createAudit, listAudits, classifyCompany } from '@/lib/actions';

type Step = 'form' | 'classifying' | 'review';

type Classification = {
  industry: string | null;
  company_size: string | null;
  business_model: string | null;
  confidence_notes: string;
};


type HttpWarning = {
  cleanUrl: string;
  cleanCompanyName: string;
  cleanCompetitors: string[];
  httpFields: string[];
};

type DuplicateWarning = {
  job_id: string;
  status: 'completed' | 'processing' | 'pending';
  created_at: string;
  cleanUrl: string;
  cleanCompanyName: string;
  cleanCompetitors: string[];
};


function WebsiteForm() {
  const [step, setStep] = useState<Step>('form');
  const [url, setUrl] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [classification, setClassification] = useState<Classification | null>(null);
  const [competitors, setCompetitors] = useState(['', '', '']);
  const [lastClassifiedKey, setLastClassifiedKey] = useState<string | null>(null);
  const [httpWarning, setHttpWarning] = useState<HttpWarning | null>(null);
  const [duplicateWarning, setDuplicateWarning] = useState<DuplicateWarning | null>(null);
  const router = useRouter();

  const setCompetitor = (index: number, value: string) => {
    setCompetitors(prev => prev.map((c, i) => i === index ? value : c));
  };

  const normalizeUrl = (raw: string): string => {
    const s = raw.trim();
    const withScheme = /^https?:\/\//i.test(s) ? s : `https://${s}`;
    const u = new URL(withScheme);
    if (!u.hostname.includes('.')) throw new Error(`Invalid URL: ${s}`);
    return (u.origin + u.pathname).replace(/\/+$/, '');
  };

  const isDeepPath = (normalized: string): boolean => {
    try {
      const segments = new URL(normalized).pathname.split('/').filter(Boolean);
      return segments.length > 1;
    } catch {
      return false;
    }
  };

  const stripScheme = (u: string) => u.replace(/^https?:\/\//i, '');
  const normalizeForCompare = (u: string) => stripScheme(u.toLowerCase()).replace(/^www\./, '');

  const submitAudit = async (cleanUrl: string, cleanCompanyName: string, cleanCompetitors: string[]) => {
    try {
      const formData = new FormData();
      formData.append('url', cleanUrl);
      formData.append('company_name', cleanCompanyName);
      formData.append('industry', classification!.industry!);
      formData.append('company_size', classification!.company_size!);
      formData.append('business_model', classification!.business_model!);
      formData.append('competitor_1', cleanCompetitors[0]);
      formData.append('competitor_2', cleanCompetitors[1]);
      formData.append('competitor_3', cleanCompetitors[2]);

      const data = await createAudit(formData);
      toast.success("Audit started.", { duration: 3000 });
      router.push(`/audits/${data.job_id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Error submitting job");
    }
  };

  const handleNext = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    let cleanUrl: string;
    try {
      cleanUrl = normalizeUrl(url);
    } catch {
      toast.error("Invalid URL.");
      return;
    }
    const cleanCompanyName = companyName.trim();
    if (!cleanCompanyName) {
      toast.error("Company name cannot be empty.");
      return;
    }
    if (isDeepPath(cleanUrl)) {
      toast.error(`URL looks like a product page,did you mean ${new URL(cleanUrl).origin}?`);
      return;
    }

    const key = `${cleanUrl}|${cleanCompanyName}`;
    if (key === lastClassifiedKey && classification !== null) {
      setStep('review');
      return;
    }

    setStep('classifying');
    try {
      const result = await classifyCompany(cleanUrl, cleanCompanyName);
      setClassification(result);
      setLastClassifiedKey(key);
      setStep('review');
    } catch {
      toast.error("Classification failed. You can fill in the details manually.");
      setClassification({ industry: null, company_size: null, business_model: null, confidence_notes: '' });
      setStep('review');
    }
  };

  const handleLaunch = async () => {
    let cleanUrl: string;
    try {
      cleanUrl = normalizeUrl(url);
    } catch {
      toast.error("Invalid URL.");
      return;
    }
    const cleanCompanyName = companyName.trim();

    const cleanCompetitors: string[] = [];
    for (const c of competitors) {
      if (!c.trim()) {
        toast.error("All 3 competitor URLs are required.");
        return;
      }
      let normalized: string;
      try {
        normalized = normalizeUrl(c);
      } catch {
        toast.error(`Invalid competitor URL: ${c.trim()}`);
        return;
      }
      if (isDeepPath(normalized)) {
        toast.error(`Competitor URL looks like a product page, did you mean ${new URL(normalized).origin}?`);
        return;
      }
      cleanCompetitors.push(normalized);
    }

    const compStripped = cleanCompetitors.map(c => stripScheme(c.toLowerCase()));
    if (new Set(compStripped).size < compStripped.length) {
      toast.error("Duplicate competitor URLs - all three must be different.");
      return;
    }
    if (compStripped.includes(stripScheme(cleanUrl.toLowerCase()))) {
      toast.error("A competitor URL matches the client URL.");
      return;
    }

    const httpFields: string[] = [];
    if (cleanUrl.startsWith('http://')) httpFields.push(cleanUrl);
    cleanCompetitors.forEach(c => { if (c.startsWith('http://')) httpFields.push(c); });

    if (httpFields.length > 0) {
      setHttpWarning({ cleanUrl, cleanCompanyName, cleanCompetitors, httpFields });
      return;
    }

    if (!classification?.industry || !classification?.company_size || !classification?.business_model) {
      toast.error("Please fill in all classification fields before launching.");
      return;
    }
    await checkDuplicateAndSubmit(cleanUrl, cleanCompanyName, cleanCompetitors);
  };

  const checkDuplicateAndSubmit = async (cleanUrl: string, cleanCompanyName: string, cleanCompetitors: string[]) => {
    try {
      const jobs: { id: string; url: string; status: string; created_at: string }[] = await listAudits();
      const existing = jobs.find(j =>
        ['completed', 'processing', 'pending'].includes(j.status) &&
        normalizeForCompare(j.url) === normalizeForCompare(cleanUrl)
      );
      if (existing) {
        setDuplicateWarning({
          job_id: existing.id,
          status: existing.status as DuplicateWarning['status'],
          created_at: existing.created_at,
          cleanUrl,
          cleanCompanyName,
          cleanCompetitors,
        });
        return;
      }
    } catch {
      // non-critical, proceed if check fails
    }

    await submitAudit(cleanUrl, cleanCompanyName, cleanCompetitors);
  };

  if (step === 'classifying') {
    return (
      <div className="flex flex-col items-center gap-4 py-4">
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-gray-200 border-t-green-700" />
        <p className="text-sm text-gray-500">Analysing <span className="font-medium text-gray-700">{companyName}</span>…</p>
        <p className="text-xs text-gray-400">This usually takes 5–10 seconds</p>
      </div>
    );
  }

  if (step === 'review') {
    const INDUSTRIES = [
      'Retail & Ecommerce', 'Travel & Hospitality', 'Media & Entertainment',
      'Public Sector', 'Life Sciences', 'Banking & Finance', 'Legal',
      'Manufacturing', 'Technology & Software', 'Professional Services',
      'Defense & Aerospace',
    ];
    const SIZES = ['SMB', 'Mid-Market', 'Enterprise'];
    const MODELS = ['B2C', 'B2B', 'Mixed'];

    const updateClassification = (patch: Partial<Classification>) =>
      setClassification(prev => prev ? { ...prev, ...patch } : prev);

    return (
      <>
        {httpWarning && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4 animate-[backdrop-in_0.15s_ease-out]">
            <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 w-full max-w-sm flex flex-col gap-4 animate-[modal-in_0.2s_ease-out]">
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-base font-semibold text-gray-900">HTTP URL detected</h2>
                <button type="button" className="text-gray-400 hover:text-gray-600 transition text-lg leading-none mt-0.5 cursor-pointer" onClick={() => setHttpWarning(null)} aria-label="Dismiss">×</button>
              </div>
              <div className="flex flex-col gap-1.5">
                <p className="text-sm text-gray-500">The following {httpWarning.httpFields.length === 1 ? 'URL uses' : 'URLs use'} HTTP instead of HTTPS:</p>
                <ul className="mt-0.5 text-sm text-gray-700 list-disc list-inside">
                  {httpWarning.httpFields.map(f => <li key={f}>{f}</li>)}
                </ul>
              </div>
              <div className="flex flex-col gap-2">
                <button type="button" className="bg-green-700 text-white rounded-xl px-4 py-2.5 font-semibold text-sm hover:bg-green-800 transition cursor-pointer" onClick={() => { const upgraded = { ...httpWarning, cleanUrl: httpWarning.cleanUrl.replace(/^http:\/\//i, 'https://'), cleanCompetitors: httpWarning.cleanCompetitors.map(c => c.replace(/^http:\/\//i, 'https://')) }; setHttpWarning(null); checkDuplicateAndSubmit(upgraded.cleanUrl, upgraded.cleanCompanyName, upgraded.cleanCompetitors); }}>Switch to HTTPS</button>
                <button type="button" className="text-gray-500 rounded-xl px-4 py-2.5 font-medium text-sm hover:bg-gray-50 transition cursor-pointer" onClick={() => { const data = httpWarning; setHttpWarning(null); checkDuplicateAndSubmit(data.cleanUrl, data.cleanCompanyName, data.cleanCompetitors); }}>Proceed with HTTP</button>
              </div>
            </div>
          </div>
        )}
        {duplicateWarning && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4 animate-[backdrop-in_0.15s_ease-out]">
            <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 w-full max-w-sm flex flex-col gap-4 animate-[modal-in_0.2s_ease-out]">
              <div className="flex items-start justify-between gap-2">
                <h2 className="text-base font-semibold text-gray-900">{duplicateWarning.status === 'completed' ? 'Audit already exists' : 'Audit in progress'}</h2>
                <button type="button" className="text-gray-400 hover:text-gray-600 transition text-lg leading-none mt-0.5 cursor-pointer" onClick={() => setDuplicateWarning(null)} aria-label="Dismiss">×</button>
              </div>
              <p className="text-sm text-gray-500">{duplicateWarning.status === 'completed' ? `An audit for this URL was completed on ${new Date(duplicateWarning.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}. View it or run a new one?` : 'An audit for this URL is currently being processed.'}</p>
              <div className="flex flex-col gap-2">
                <button type="button" className="bg-green-700 text-white rounded-xl px-4 py-2.5 font-semibold text-sm hover:bg-green-800 transition cursor-pointer" onClick={() => { setDuplicateWarning(null); router.push(duplicateWarning.status === 'completed' ? `/audits/${duplicateWarning.job_id}/result` : `/audits/${duplicateWarning.job_id}`); }}>{duplicateWarning.status === 'completed' ? 'View existing audit' : 'Monitor audit'}</button>
                {duplicateWarning.status === 'completed' && (
                  <button type="button" className="text-gray-500 rounded-xl px-4 py-2.5 font-medium text-sm hover:bg-gray-50 transition cursor-pointer" onClick={() => { const d = duplicateWarning; setDuplicateWarning(null); submitAudit(d.cleanUrl, d.cleanCompanyName, d.cleanCompetitors); }}>Run new audit</button>
                )}
              </div>
            </div>
          </div>
        )}
        <div className="flex flex-col gap-4 w-full">
          <button
            type="button"
            className="self-start text-sm text-gray-500 hover:text-gray-700 transition cursor-pointer"
            onClick={() => setStep('form')}
          >
            ← Back
          </button>

          <div className="flex flex-col gap-0.5">
            <h2 className="text-base font-semibold text-gray-900">{companyName}</h2>
            <p className="text-xs text-gray-400">{url}</p>
          </div>

          <div className="flex flex-col gap-3">
            {/* Industry — full width */}
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-gray-600">Industry</label>
              <div className="relative">
                <select
                  value={classification?.industry ?? ''}
                  onChange={e => updateClassification({ industry: e.target.value || null })}
                  className="w-full appearance-none bg-white border border-gray-200 rounded-xl px-4 py-2.5 pr-9 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition cursor-pointer"
                >
                  <option value="" disabled>— not set —</option>
                  {INDUSTRIES.map(i => <option key={i} value={i}>{i}</option>)}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                  <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </div>
            </div>

            {/* Size + Model — side by side */}
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-gray-600">Company size</label>
                <div className="relative">
                  <select
                    value={classification?.company_size ?? ''}
                    onChange={e => updateClassification({ company_size: e.target.value || null })}
                    className="w-full appearance-none bg-white border border-gray-200 rounded-xl px-4 py-2.5 pr-9 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition cursor-pointer"
                  >
                    <option value="" disabled>— not set —</option>
                    {SIZES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-sm font-medium text-gray-600">Business model</label>
                <div className="relative">
                  <select
                    value={classification?.business_model ?? ''}
                    onChange={e => updateClassification({ business_model: e.target.value || null })}
                    className="w-full appearance-none bg-white border border-gray-200 rounded-xl px-4 py-2.5 pr-9 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition cursor-pointer"
                  >
                    <option value="" disabled>— not set —</option>
                    {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                    <svg className="h-4 w-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </div>
              </div>
            </div>

          </div>

          {classification?.confidence_notes && (
            <p className="text-xs text-gray-400 italic">{classification.confidence_notes}</p>
          )}

          <hr className="border-gray-100 my-1" />

          {/* Competitors */}
          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-gray-600">Competitors</label>
            {[0, 1, 2].map(i => (
              <input
                key={i}
                type="url"
                value={competitors[i]}
                onChange={e => setCompetitor(i, e.target.value)}
                placeholder="https://competitor.com"
                className="border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
              />
            ))}
          </div>

          <button
            type="button"
            onClick={handleLaunch}
            className="bg-green-700 text-white rounded-xl px-6 py-3 font-semibold text-base hover:bg-green-800 active:scale-[0.98] transition-all cursor-pointer mt-1"
          >
            Launch Audit
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      {httpWarning && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4 animate-[backdrop-in_0.15s_ease-out]">
          <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 w-full max-w-sm flex flex-col gap-4 animate-[modal-in_0.2s_ease-out]">
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-base font-semibold text-gray-900">HTTP URL detected</h2>
              <button
                type="button"
                className="text-gray-400 hover:text-gray-600 transition text-lg leading-none mt-0.5 cursor-pointer"
                onClick={() => setHttpWarning(null)}
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
            <div className="flex flex-col gap-1.5">
              <p className="text-sm text-gray-500">
                The following {httpWarning.httpFields.length === 1 ? 'URL uses' : 'URLs use'} HTTP instead of HTTPS:
              </p>
              <ul className="mt-0.5 text-sm text-gray-700 list-disc list-inside">
                {httpWarning.httpFields.map(f => <li key={f}>{f}</li>)}
              </ul>
            </div>
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="bg-green-700 text-white rounded-xl px-4 py-2.5 font-semibold text-sm hover:bg-green-800 transition cursor-pointer"
                onClick={() => {
                  const upgraded = {
                    ...httpWarning,
                    cleanUrl: httpWarning.cleanUrl.replace(/^http:\/\//i, 'https://'),
                    cleanCompetitors: httpWarning.cleanCompetitors.map(c => c.replace(/^http:\/\//i, 'https://')),
                  };
                  setHttpWarning(null);
                  checkDuplicateAndSubmit(upgraded.cleanUrl, upgraded.cleanCompanyName, upgraded.cleanCompetitors);
                }}
              >
                Switch to HTTPS
              </button>
              <button
                type="button"
                className="text-gray-500 rounded-xl px-4 py-2.5 font-medium text-sm hover:bg-gray-50 transition cursor-pointer"
                onClick={() => {
                  const data = httpWarning;
                  setHttpWarning(null);
                  checkDuplicateAndSubmit(data.cleanUrl, data.cleanCompanyName, data.cleanCompetitors);
                }}
              >
                Proceed with HTTP
              </button>
            </div>
          </div>
        </div>
      )}
      {duplicateWarning && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4 animate-[backdrop-in_0.15s_ease-out]">
          <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-6 w-full max-w-sm flex flex-col gap-4 animate-[modal-in_0.2s_ease-out]">
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-base font-semibold text-gray-900">
                {duplicateWarning.status === 'completed' ? 'Audit already exists' : 'Audit in progress'}
              </h2>
              <button
                type="button"
                className="text-gray-400 hover:text-gray-600 transition text-lg leading-none mt-0.5 cursor-pointer"
                onClick={() => setDuplicateWarning(null)}
                aria-label="Dismiss"
              >
                ×
              </button>
            </div>
            <p className="text-sm text-gray-500">
              {duplicateWarning.status === 'completed'
                ? `An audit for this URL was completed on ${new Date(duplicateWarning.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}. View it or run a new one?`
                : 'An audit for this URL is currently being processed.'}
            </p>
            <div className="flex flex-col gap-2">
              <button
                type="button"
                className="bg-green-700 text-white rounded-xl px-4 py-2.5 font-semibold text-sm hover:bg-green-800 transition cursor-pointer"
                onClick={() => {
                  setDuplicateWarning(null);
                  router.push(duplicateWarning.status === 'completed'
                    ? `/audits/${duplicateWarning.job_id}/result`
                    : `/audits/${duplicateWarning.job_id}`
                  );
                }}
              >
                {duplicateWarning.status === 'completed' ? 'View existing audit' : 'Monitor audit'}
              </button>
              {duplicateWarning.status === 'completed' && (
                <button
                  type="button"
                  className="text-gray-500 rounded-xl px-4 py-2.5 font-medium text-sm hover:bg-gray-50 transition cursor-pointer"
                  onClick={() => {
                    const d = duplicateWarning;
                    setDuplicateWarning(null);
                    submitAudit(d.cleanUrl, d.cleanCompanyName, d.cleanCompetitors);
                  }}
                >
                  Run new audit
                </button>
              )}
            </div>
          </div>
        </div>
      )}
      <form className="flex flex-col gap-6 w-full" onSubmit={handleNext}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="company_name" className="text-sm font-medium text-gray-600">Company Name</label>
            <input
              type="text"
              id="company_name"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="Acme Corp"
              required
              className="border border-gray-200 rounded-xl px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="url" className="text-sm font-medium text-gray-600">Website URL</label>
            <input
              type="url"
              id="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              required
              className="border border-gray-200 rounded-xl px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
            />
          </div>
        </div>
        <button
          type="submit"
          className="bg-green-700 text-white rounded-xl px-6 py-3 font-semibold text-base hover:bg-green-800 active:scale-[0.98] transition-all mt-1 cursor-pointer"
        >
          Next →
        </button>
      </form>
    </>
  );
}


export default function Home() {
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center px-6 py-12">
      <div className="flex flex-col items-center gap-8 w-full max-w-lg">

        {/* Header */}
        <div className="flex flex-col items-center gap-2 text-center">
          <h1 className="text-4xl font-bold text-gray-900 tracking-tight">Website AI Pre-Audit</h1>
          <p className="text-sm text-gray-400 mt-1">Automated website audit reports</p>
        </div>

        {/* Form card */}
        <div className="bg-white rounded-2xl shadow-md border border-gray-100 border-t-4 border-t-green-700 px-8 py-8 w-full">
          <WebsiteForm />
        </div>

      </div>
    </div>
  );
}
