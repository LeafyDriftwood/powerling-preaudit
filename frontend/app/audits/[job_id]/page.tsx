"use client";

import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';

interface AuditJob {
  id: string;
  url: string;
  company_name: string;
  competitor_1: string;
  competitor_2: string;
  competitor_3: string;
  status: string;
  error_message?: string;
  created_at: string;
}

const PROGRESS_MESSAGES = [
  "Running Playwright crawler...",
  "Gathering globalization data...",
  "Analysing language coverage...",
  "Researching competitor positioning...",
  "Checking website accessibility...",
  "Gathering online reputation data...",
  "Searching for social media presence...",
  "Analysing SEO performance...",
];

export default function StatusPage() {
  const params = useParams();
  const router = useRouter();
  const job_id = params.job_id as string;

  const [job, setJob] = useState<AuditJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msgIndex, setMsgIndex] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const msgIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}`);
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          setError(err.detail || `Request failed (${response.status})`);
          if (intervalRef.current) clearInterval(intervalRef.current);
          return;
        }
        const data = await response.json();
        setJob(data);
        if (data.status === 'completed' || data.status === 'error') {
          if (intervalRef.current) clearInterval(intervalRef.current);
          if (msgIntervalRef.current) clearInterval(msgIntervalRef.current);
          if (data.status === 'completed') {
            router.push(`/audits/${job_id}/result`);
          }
        }
      } catch {
        setError("Failed to fetch job status");
        if (intervalRef.current) clearInterval(intervalRef.current);
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, 2000);
    msgIntervalRef.current = setInterval(() => {
      setMsgIndex(i => (i + 1) % PROGRESS_MESSAGES.length);
    }, 10000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (msgIntervalRef.current) clearInterval(msgIntervalRef.current);
    };
  }, [job_id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-green-700" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center px-6">
        <div className="bg-white rounded-2xl shadow-md border border-gray-100 px-8 py-10 max-w-md w-full text-center flex flex-col gap-4">
          <div className="h-12 w-12 rounded-full bg-red-100 flex items-center justify-center mx-auto text-red-500 text-xl font-bold">✕</div>
          <h1 className="text-xl font-bold text-gray-900">Something went wrong</h1>
          <p className="text-gray-500 text-sm">{error}</p>
          <Link href="/audits" className="text-green-700 hover:text-green-800 font-semibold text-sm transition">← All Audits</Link>
        </div>
      </div>
    );
  }

  const isActive = job?.status === 'pending' || job?.status === 'processing';

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-6">
      <div className="flex flex-col items-center gap-6 max-w-sm w-full text-center">

        {isActive ? (
          <>
                    {/* Spinner */}
            <div className="animate-spin rounded-full h-20 w-20 border-2 border-gray-200 border-t-green-700" />

            {/* Company */}
            <div className="flex flex-col gap-1">
              <h1 className="text-2xl font-bold text-gray-900">Analysing {job?.company_name}</h1>
              <p className="text-sm text-gray-400">{job?.url}</p>
            </div>

            {/* Rotating message — only shown when actively processing */}
            {job?.status === 'processing' ? (
              <p key={msgIndex} className="text-sm text-gray-500 animate-pulse">
                {PROGRESS_MESSAGES[msgIndex]}
              </p>
            ) : (
              <p className="text-sm text-gray-400">Waiting to start...</p>
            )}

            {/* Status pill */}
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium capitalize ${
              job?.status === 'pending' ? 'bg-yellow-100 text-yellow-800' : 'bg-blue-100 text-blue-800'
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full animate-pulse ${job?.status === 'pending' ? 'bg-yellow-500' : 'bg-blue-500'}`} />
              {job?.status}
            </span>

            <p className="text-xs text-gray-400">You can safely close this tab and check back later.</p>
          </>
        ) : (
          <>
            {/* Error state */}
            <div className="h-14 w-14 rounded-full bg-red-100 flex items-center justify-center text-red-500 text-2xl font-bold">✕</div>
            <div className="flex flex-col gap-1">
              <h1 className="text-2xl font-bold text-gray-900">Audit failed</h1>
              <p className="text-sm text-gray-400">{job?.company_name} · {job?.url}</p>
            </div>
            {job?.error_message && (
              <p className="text-sm text-red-500 bg-red-50 rounded-lg px-4 py-3 w-full text-left">{job.error_message}</p>
            )}
          </>
        )}

        <Link href="/audits" className="text-sm text-green-700 hover:text-green-800 font-semibold transition">
          ← All Audits
        </Link>

      </div>
    </div>
  );
}
