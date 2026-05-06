"use client";

import { useEffect, useState } from 'react';
import Link from 'next/link';

interface AuditSummary {
  id: string;
  url: string;
  company_name: string;
  status: string;
  created_at: string;
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    processing: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    error: 'bg-red-100 text-red-800',
  };
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium capitalize ${styles[status] ?? 'bg-gray-100 text-gray-800'}`}>
      {status === 'pending' || status === 'processing' ? (
        <span className={`mr-1.5 h-1.5 w-1.5 rounded-full animate-pulse ${status === 'pending' ? 'bg-yellow-500' : 'bg-blue-500'}`} />
      ) : null}
      {status}
    </span>
  );
}

export default function AuditListPage() {
  const [audits, setAudits] = useState<AuditSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAudits = () =>
      fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits`)
        .then(async (r) => {
          if (!r.ok) throw new Error(`Server error: ${r.status}`);
          return r.json();
        })
        .then((data: AuditSummary[]) => {
          setAudits(data);
          setLoading(false);
          return data;
        })
        .catch(() => {
          setError('Failed to load audits. Is the backend running?');
          setLoading(false);
          return [] as AuditSummary[];
        });

    fetchAudits().then((data) => {
      const hasInProgress = data.some((a) => a.status === 'pending' || a.status === 'processing');
      if (!hasInProgress) return;

      const interval = setInterval(() => {
        fetchAudits().then((latest) => {
          const stillInProgress = latest.some((a) => a.status === 'pending' || a.status === 'processing');
          if (!stillInProgress) clearInterval(interval);
        });
      }, 5000);

      return () => clearInterval(interval);
    });
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-orange-50 px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-3xl font-bold text-gray-900">All Audits</h1>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500" />
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            {error}
          </div>
        )}

        {!loading && !error && audits.length === 0 && (
          <div className="text-center py-20 text-gray-500">
            <p className="text-lg mb-4">No audits yet.</p>
            <Link href="/" className="text-orange-600 font-semibold hover:text-orange-700">
              Start one →
            </Link>
          </div>
        )}

        {!loading && !error && audits.length > 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-5 py-3 font-semibold text-gray-600">Company</th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 hidden md:table-cell">URL</th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600">Status</th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 hidden sm:table-cell">Created</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {audits.map((audit) => (
                  <tr key={audit.id} className="hover:bg-gray-50 transition">
                    <td className="px-5 py-4 font-medium text-gray-900">{audit.company_name}</td>
                    <td className="px-5 py-4 text-gray-500 hidden md:table-cell max-w-xs truncate">
                      {audit.url}
                    </td>
                    <td className="px-5 py-4">
                      <StatusBadge status={audit.status} />
                    </td>
                    <td className="px-5 py-4 text-gray-500 hidden sm:table-cell">
                      {new Date(audit.created_at).toLocaleDateString('en-US', {
                        month: 'short', day: 'numeric', year: 'numeric',
                        hour: '2-digit', minute: '2-digit',
                      })}
                    </td>
                    <td className="px-5 py-4 text-right">
                      <Link
                        href={audit.status === 'completed' ? `/audits/${audit.id}/result` : `/audits/${audit.id}`}
                        className="text-orange-600 hover:text-orange-700 font-semibold"
                      >
                        View →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
