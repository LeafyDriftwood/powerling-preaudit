"use client";

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import { getUser } from '@/lib/actions';

interface AuditSummary {
  id: string;
  url: string;
  company_name: string;
  status: string;
  created_at: string;
}

interface UserDetail {
  email: string;
  role: string;
  first_connected_at: string;
  last_connected_at: string;
  audit_count: number;
  jobs: AuditSummary[];
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

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function UserDetailPage() {
  const router = useRouter();
  const params = useParams();
  const email = decodeURIComponent(params.email as string);

  const [user, setUser] = useState<UserDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUser(email)
      .then(setUser)
      .catch((e) => {
        if (e.message?.includes('403') || e.message?.includes('Admin')) {
          router.replace('/');
        } else {
          setError(e.message || 'Failed to load user.');
        }
      })
      .finally(() => setLoading(false));
  }, [email, router]);

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="max-w-5xl mx-auto">

        <div className="mb-6">
          <Link href="/admin/users" className="text-sm text-green-700 hover:text-green-800 font-semibold transition">
            ← Back to users
          </Link>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-green-700" />
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">{error}</div>
        )}

        {!loading && !error && user && (
          <div className="flex flex-col gap-6">

            {/* User info card */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
              <h1 className="text-2xl font-bold text-gray-900 mb-4">{user.email}</h1>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Role</p>
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${user.role === 'admin' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                    {user.role}
                  </span>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Total audits</p>
                  <p className="font-semibold text-gray-900">{user.audit_count}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">First connected</p>
                  <p className="font-semibold text-gray-700">{formatDate(user.first_connected_at)}</p>
                </div>
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-xs text-gray-500 mb-1">Last connected</p>
                  <p className="font-semibold text-gray-700">{formatDate(user.last_connected_at)}</p>
                </div>
              </div>
            </div>

            {/* Audits table */}
            <div>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">Audits</h2>
              {user.jobs.length === 0 ? (
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-10 text-center text-gray-400">
                  No audits submitted yet.
                </div>
              ) : (
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
                      {user.jobs.map((job) => (
                        <tr key={job.id} className="hover:bg-gray-50 transition cursor-pointer" onClick={() => router.push(job.status === 'completed' ? `/audits/${job.id}/result` : `/audits/${job.id}`)}>
                          <td className="px-5 py-4 font-medium text-gray-900">{job.company_name}</td>
                          <td className="px-5 py-4 text-gray-400 hidden md:table-cell max-w-xs truncate">{job.url}</td>
                          <td className="px-5 py-4"><StatusBadge status={job.status} /></td>
                          <td className="px-5 py-4 text-gray-500 hidden sm:table-cell">{formatDate(job.created_at)}</td>
                          <td className="px-5 py-4 text-right">
                            <Link
                              href={job.status === 'completed' ? `/audits/${job.id}/result` : `/audits/${job.id}`}
                              className="text-green-700 hover:text-green-800 font-semibold"
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
        )}
      </div>
    </div>
  );
}
