"use client";

import { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

interface AuditSummary {
  id: string;
  url: string;
  company_name: string;
  status: string;
  created_at: string;
}

type SortKey = 'company_name' | 'created_at' | 'status';
type SortDir = 'asc' | 'desc';

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

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <span className={`ml-1 text-xs ${active ? 'text-green-700' : 'text-gray-300'}`}>
      {active && dir === 'desc' ? '↓' : '↑'}
    </span>
  );
}

export default function AuditListPage() {
  const router = useRouter();
  const [audits, setAudits] = useState<AuditSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

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

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return audits
      .filter(a => a.company_name.toLowerCase().includes(q) || a.url.toLowerCase().includes(q))
      .filter(a => statusFilter ? a.status === statusFilter : true)
      .sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        const cmp = av < bv ? -1 : av > bv ? 1 : 0;
        return sortDir === 'asc' ? cmp : -cmp;
      });
  }, [audits, search, sortKey, sortDir, statusFilter]);

  const stats = useMemo(() => ({
    completed: audits.filter(a => a.status === 'completed').length,
    processing: audits.filter(a => a.status === 'processing').length,
    pending: audits.filter(a => a.status === 'pending').length,
    error: audits.filter(a => a.status === 'error').length,
  }), [audits]);

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="max-w-5xl mx-auto">

        {/* Heading */}
        <div className="flex items-center gap-3 mb-6">
          <h1 className="text-3xl font-bold text-gray-900">All Audits</h1>
          {!loading && !error && (
            <span className="text-sm font-medium text-gray-400 bg-gray-100 rounded-full px-2.5 py-0.5">
              {audits.length}
</span>
          )}
        </div>

        {/* Stats row */}
        {!loading && !error && audits.length > 0 && (
          <div className="flex items-center gap-3 mb-6">
            <button
              onClick={() => setStatusFilter(f => f === 'completed' ? null : 'completed')}
              className={`flex items-center gap-1.5 border rounded-lg px-3 py-1.5 text-sm transition cursor-pointer ${statusFilter === 'completed' ? 'bg-green-50 border-green-400' : 'bg-white border-gray-200 hover:border-gray-300'}`}
            >
              <span className="h-2 w-2 rounded-full bg-green-500" />
              <span className="font-medium text-gray-700">{stats.completed}</span>
              <span className="text-gray-400">Completed</span>
            </button>
            {stats.processing > 0 && (
              <button
                onClick={() => setStatusFilter(f => f === 'processing' ? null : 'processing')}
                className={`flex items-center gap-1.5 border rounded-lg px-3 py-1.5 text-sm transition cursor-pointer ${statusFilter === 'processing' ? 'bg-blue-50 border-blue-400' : 'bg-white border-gray-200 hover:border-gray-300'}`}
              >
                <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                <span className="font-medium text-gray-700">{stats.processing}</span>
                <span className="text-gray-400">Processing</span>
              </button>
            )}
            {stats.pending > 0 && (
              <button
                onClick={() => setStatusFilter(f => f === 'pending' ? null : 'pending')}
                className={`flex items-center gap-1.5 border rounded-lg px-3 py-1.5 text-sm transition cursor-pointer ${statusFilter === 'pending' ? 'bg-yellow-50 border-yellow-400' : 'bg-white border-gray-200 hover:border-gray-300'}`}
              >
                <span className="h-2 w-2 rounded-full bg-yellow-500 animate-pulse" />
                <span className="font-medium text-gray-700">{stats.pending}</span>
                <span className="text-gray-400">Pending</span>
              </button>
            )}
            {stats.error > 0 && (
              <button
                onClick={() => setStatusFilter(f => f === 'error' ? null : 'error')}
                className={`flex items-center gap-1.5 border rounded-lg px-3 py-1.5 text-sm transition cursor-pointer ${statusFilter === 'error' ? 'bg-red-50 border-red-400' : 'bg-white border-gray-200 hover:border-gray-300'}`}
              >
                <span className="h-2 w-2 rounded-full bg-red-400" />
                <span className="font-medium text-gray-700">{stats.error}</span>
                <span className="text-gray-400">Error</span>
              </button>
            )}
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-green-700" />
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
            <Link href="/" className="text-green-700 font-semibold hover:text-green-800">
              Start one →
            </Link>
          </div>
        )}

        {!loading && !error && audits.length > 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">

            {/* Search toolbar */}
            <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-3">
              <input
                type="text"
                placeholder="Search by company or URL..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-green-700 focus:border-transparent transition-all duration-200"
              />
              <span className={`text-sm text-gray-400 whitespace-nowrap transition-opacity duration-200 ${search ? 'opacity-100' : 'opacity-0'}`}>
                {filtered.length} result{filtered.length !== 1 ? 's' : ''}
              </span>
            </div>

            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th
                    className="text-left px-5 py-3 font-semibold text-gray-600 cursor-pointer select-none hover:text-gray-900 transition"
                    onClick={() => toggleSort('company_name')}
                  >
                    Company <SortIcon active={sortKey === 'company_name'} dir={sortDir} />
                  </th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 hidden md:table-cell">URL</th>
                  <th
                    className="text-left px-5 py-3 font-semibold text-gray-600 cursor-pointer select-none hover:text-gray-900 transition"
                    onClick={() => toggleSort('status')}
                  >
                    Status <SortIcon active={sortKey === 'status'} dir={sortDir} />
                  </th>
                  <th
                    className="text-left px-5 py-3 font-semibold text-gray-600 hidden sm:table-cell cursor-pointer select-none hover:text-gray-900 transition"
                    onClick={() => toggleSort('created_at')}
                  >
                    Created <SortIcon active={sortKey === 'created_at'} dir={sortDir} />
                  </th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-10 text-center text-gray-400">
                      No audits match your search.
                    </td>
                  </tr>
                ) : filtered.map((audit) => (
                  <tr key={audit.id} className="hover:bg-gray-50 transition cursor-pointer" onClick={() => router.push(audit.status === 'completed' ? `/audits/${audit.id}/result` : `/audits/${audit.id}`)}>

                    <td className="px-5 py-4 font-medium text-gray-900">{audit.company_name}</td>
                    <td className="px-5 py-4 text-gray-400 hidden md:table-cell max-w-xs truncate">
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
  );
}
