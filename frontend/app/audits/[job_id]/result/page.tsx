"use client";

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';

interface AuditMeta {
  company_name: string;
  url: string;
  created_at: string;
}

export default function ResultPage() {
  const params = useParams();
  const job_id = params.job_id as string;

  const [meta, setMeta] = useState<AuditMeta | null>(null);
  const [result, setResult] = useState<object | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const base = 'http://localhost:8000';
    Promise.all([
      fetch(`${base}/audits/${job_id}`).then((r) => r.json()),
      fetch(`${base}/audits/${job_id}/result`).then((r) => r.json()),
    ])
      .then(([metaData, resultData]) => {
        if (metaData.error) {
          setError(metaData.error);
        } else {
          setMeta({ company_name: metaData.company_name, url: metaData.url, created_at: metaData.created_at });
        }
        if (resultData.error) {
          setError(resultData.error);
        } else {
          setResult(resultData);
        }
        setLoading(false);
      })
      .catch(() => {
        setError('Failed to load result. Is the backend running?');
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

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-white to-orange-50 flex items-center justify-center px-6">
        <div className="flex flex-col items-center gap-4 text-center max-w-md">
          <h1 className="text-2xl font-bold text-red-600">Error</h1>
          <p className="text-gray-700">{error}</p>
          <Link href="/audits" className="text-orange-600 font-semibold hover:text-orange-700">
            ← All Audits
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-orange-50 px-6 py-10">
      <div className="max-w-5xl mx-auto flex flex-col gap-6">
        <div>
          <Link href="/audits" className="text-orange-600 hover:text-orange-700 font-semibold text-sm">
            ← All Audits
          </Link>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h1 className="text-2xl font-bold text-gray-900">{meta?.company_name}</h1>
          <p className="text-gray-500 text-sm mt-1">{meta?.url}</p>
          {meta?.created_at && (
            <p className="text-gray-400 text-xs mt-1">
              Generated {new Date(meta.created_at).toLocaleDateString('en-US', {
                month: 'long', day: 'numeric', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              })}
            </p>
          )}
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-600">Raw Report JSON</span>
            <button
              onClick={() => {
                navigator.clipboard.writeText(JSON.stringify(result, null, 2));
              }}
              className="text-xs text-orange-600 hover:text-orange-700 font-medium"
            >
              Copy
            </button>
          </div>
          <pre className="p-5 text-xs text-gray-800 overflow-auto max-h-[70vh] leading-relaxed">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}
