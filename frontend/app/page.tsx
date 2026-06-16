"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import toast from 'react-hot-toast';
import { createAudit, listAudits } from '@/lib/actions';


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
  const [url, setUrl] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [competitors, setCompetitors] = useState(['', '', '']);
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

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    let cleanUrl: string;
    let cleanCompetitors: string[];
    try {
      cleanUrl = normalizeUrl(url);
      cleanCompetitors = competitors.map(normalizeUrl);
    } catch {
      toast.error("One or more URLs are invalid.");
      return;
    }
    const cleanCompanyName = companyName.trim();
    if (!cleanCompanyName) {
      toast.error("Company name cannot be empty.");
      return;
    }

    if (isDeepPath(cleanUrl)) {
      toast.error(`Client URL looks like a product page — did you mean ${new URL(cleanUrl).origin}?`);
      return;
    }
    for (let i = 0; i < cleanCompetitors.length; i++) {
      if (isDeepPath(cleanCompetitors[i])) {
        toast.error(`Competitor ${i + 1} URL looks like a product page — did you mean ${new URL(cleanCompetitors[i]).origin}?`);
        return;
      }
    }

    const compStripped = cleanCompetitors.map(c => stripScheme(c.toLowerCase()));
    if (new Set(compStripped).size < compStripped.length) {
      toast.error("Duplicate competitor URLs — all three must be different.");
      return;
    }
    if (compStripped.includes(stripScheme(cleanUrl.toLowerCase()))) {
      toast.error("A competitor URL matches the client URL.");
      return;
    }

    const allUrls = [
      { label: 'Client URL', value: cleanUrl },
      ...cleanCompetitors.map((c, i) => ({ label: `Competitor ${i + 1}`, value: c })),
    ];
    const httpFields = allUrls.filter(u => u.value.startsWith('http://')).map(u => u.label);
    if (httpFields.length > 0) {
      setHttpWarning({ cleanUrl, cleanCompanyName, cleanCompetitors, httpFields });
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
      // non-critical — proceed if check fails
    }

    await submitAudit(cleanUrl, cleanCompanyName, cleanCompetitors);
  };

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
      <form className="flex flex-col gap-6 w-full" onSubmit={handleSubmit}>

      {/* Client info */}
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

      {/* Competitors */}
      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium text-gray-600">Competitors</p>
        <div className="flex flex-col gap-3">
          {competitors.map((val, i) => (
            <div key={i} className="flex flex-col gap-1.5">
              <label htmlFor={`competitor_${i + 1}`} className="text-xs text-gray-400">
                Competitor {i + 1}
              </label>
              <input
                type="url"
                id={`competitor_${i + 1}`}
                value={val}
                onChange={(e) => setCompetitor(i, e.target.value)}
                placeholder={`https://competitor${i + 1}.com`}
                required
                className="border border-gray-200 rounded-xl px-4 py-3 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition"
              />
            </div>
          ))}
        </div>
      </div>

      <button
        type="submit"
        className="bg-green-700 text-white rounded-xl px-6 py-3 font-semibold text-base hover:bg-green-800 active:scale-[0.98] transition-all mt-1"
      >
        Start Audit
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
