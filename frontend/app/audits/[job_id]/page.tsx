"use client";

import { useEffect, useRef, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';

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

export default function StatusPage() {
  const params = useParams();
  const router = useRouter();
  const job_id = params.job_id as string;
  
  const [job, setJob] = useState<AuditJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
          if (data.status === 'completed') {
            router.push(`/audits/${job_id}/result`);
          }
        }
      } catch (err) {
        setError("Failed to fetch job status");
        if (intervalRef.current) clearInterval(intervalRef.current);
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();
    intervalRef.current = setInterval(fetchStatus, 2000);
    
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [job_id]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-white to-orange-200 flex items-center justify-center px-6">
        <div className="flex flex-col items-center gap-6 max-w-md">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500"></div>
          <p className="text-lg text-gray-700">Loading job status...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-white to-orange-200 flex items-center justify-center px-6">
        <div className="flex flex-col items-center gap-6 max-w-md text-center">
          <h1 className="text-3xl font-bold text-red-600">Error</h1>
          <p className="text-lg text-gray-700">{error}</p>
          <button
            onClick={() => router.push('/')}
            className="bg-orange-500 text-white rounded-lg px-6 py-3 font-semibold hover:bg-orange-600 transition"
          >
            Back to Home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-orange-200 flex flex-col items-center justify-center px-6 py-12">
      <div className="flex flex-col items-center gap-8 max-w-md w-full">
        <div className="text-center">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">Audit Status</h1>
          <p className="text-gray-600">Job ID: {job?.id}</p>
        </div>

        <div className="w-full bg-white rounded-lg shadow-md p-6 flex flex-col gap-4">
          <div>
            <p className="text-sm text-gray-500 uppercase font-semibold">Company</p>
            <p className="text-lg text-gray-900">{job?.company_name}</p>
          </div>

          <div>
            <p className="text-sm text-gray-500 uppercase font-semibold">Website</p>
            <p className="text-lg text-gray-900 break-all">{job?.url}</p>
          </div>

          <div>
            <p className="text-sm text-gray-500 uppercase font-semibold">Competitors</p>
            <ul className="mt-1 flex flex-col gap-1">
              {[job?.competitor_1, job?.competitor_2, job?.competitor_3].map((c, i) => (
                <li key={i} className="text-gray-700 break-all text-sm">{i + 1}. {c}</li>
              ))}
            </ul>
          </div>

          <div>
            <p className="text-sm text-gray-500 uppercase font-semibold">Status</p>
            <div className="flex items-center gap-2 mt-2">
              <div className={`h-3 w-3 rounded-full ${
                job?.status === 'pending' ? 'bg-yellow-500 animate-pulse' :
                job?.status === 'processing' ? 'bg-blue-500 animate-pulse' :
                job?.status === 'completed' ? 'bg-green-500' :
                'bg-red-500'
              }`}></div>
              <p className="text-lg font-semibold text-gray-900 capitalize">{job?.status}</p>
            </div>
            {job?.status === 'error' && job.error_message && (
              <p className="text-sm text-red-600 mt-2">{job.error_message}</p>
            )}
          </div>

          <div>
            <p className="text-sm text-gray-500 uppercase font-semibold">Created</p>
            <p className="text-gray-700">{job?.created_at ? new Date(job.created_at).toLocaleString() : 'N/A'}</p>
          </div>
        </div>

        <button
          onClick={() => router.push('/')}
          className="text-orange-600 hover:text-orange-700 font-semibold transition"
        >
          ← Back to Home
        </button>
      </div>
    </div>
  );
}
