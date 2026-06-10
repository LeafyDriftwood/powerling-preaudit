"use client";

import { useEffect, useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { getAllUsers, updateUserRole } from '@/lib/actions';

interface UserRow {
  email: string;
  role: string;
  first_connected_at: string;
  last_connected_at: string;
  audit_count: number;
}

type SortKey = 'email' | 'role' | 'first_connected_at' | 'last_connected_at' | 'audit_count';
type SortDir = 'asc' | 'desc';

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${role === 'admin' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
      {role}
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

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export default function AdminUsersPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('last_connected_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  useEffect(() => {
    getAllUsers()
      .then(setUsers)
      .catch((e) => {
        if (e.message?.includes('403') || e.message?.includes('Admin')) {
          router.replace('/');
        } else {
          setError(e.message || 'Failed to load users.');
        }
      })
      .finally(() => setLoading(false));
  }, [router]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return users
      .filter(u => u.email.toLowerCase().includes(q) || u.role.toLowerCase().includes(q))
      .sort((a, b) => {
        const av = a[sortKey];
        const bv = b[sortKey];
        const cmp = av < bv ? -1 : av > bv ? 1 : 0;
        return sortDir === 'asc' ? cmp : -cmp;
      });
  }, [users, search, sortKey, sortDir]);

  async function toggleRole(user: UserRow) {
    const newRole = user.role === 'admin' ? 'user' : 'admin';
    setUpdating(user.email);
    try {
      await updateUserRole(user.email, newRole);
      setUsers(prev => prev.map(u => u.email === user.email ? { ...u, role: newRole } : u));
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Failed to update role.');
    } finally {
      setUpdating(null);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 px-6 py-10">
      <div className="max-w-5xl mx-auto">

        <div className="flex items-center gap-3 mb-6">
          <h1 className="text-3xl font-bold text-gray-900">Users</h1>
          {!loading && !error && (
            <span className="text-sm font-medium text-gray-400 bg-gray-100 rounded-full px-2.5 py-0.5">
              {users.length}
            </span>
          )}
        </div>

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-green-700" />
          </div>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">{error}</div>
        )}

        {!loading && !error && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">

            <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-3">
              <input
                type="text"
                placeholder="Search by email or role..."
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
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 cursor-pointer select-none hover:text-gray-900 transition" onClick={() => toggleSort('email')}>
                    Email <SortIcon active={sortKey === 'email'} dir={sortDir} />
                  </th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 cursor-pointer select-none hover:text-gray-900 transition" onClick={() => toggleSort('role')}>
                    Role <SortIcon active={sortKey === 'role'} dir={sortDir} />
                  </th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 hidden md:table-cell cursor-pointer select-none hover:text-gray-900 transition" onClick={() => toggleSort('first_connected_at')}>
                    First connected <SortIcon active={sortKey === 'first_connected_at'} dir={sortDir} />
                  </th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 hidden md:table-cell cursor-pointer select-none hover:text-gray-900 transition" onClick={() => toggleSort('last_connected_at')}>
                    Last connected <SortIcon active={sortKey === 'last_connected_at'} dir={sortDir} />
                  </th>
                  <th className="text-left px-5 py-3 font-semibold text-gray-600 cursor-pointer select-none hover:text-gray-900 transition" onClick={() => toggleSort('audit_count')}>
                    Audits <SortIcon active={sortKey === 'audit_count'} dir={sortDir} />
                  </th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-10 text-center text-gray-400">
                      No users match your search.
                    </td>
                  </tr>
                ) : filtered.map((user) => (
                  <tr key={user.email} className="hover:bg-gray-50 transition cursor-pointer" onClick={() => router.push(`/admin/users/${encodeURIComponent(user.email)}`)}>
                    <td className="px-5 py-4 font-medium text-gray-900">{user.email}</td>
                    <td className="px-5 py-4"><RoleBadge role={user.role} /></td>
                    <td className="px-5 py-4 text-gray-500 hidden md:table-cell">{formatDate(user.first_connected_at)}</td>
                    <td className="px-5 py-4 text-gray-500 hidden md:table-cell">{formatDate(user.last_connected_at)}</td>
                    <td className="px-5 py-4 text-gray-700">{user.audit_count}</td>
                    <td className="px-5 py-4 text-right">
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleRole(user); }}
                        disabled={updating === user.email}
                        className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:border-gray-400 hover:text-gray-900 transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {updating === user.email ? '...' : user.role === 'admin' ? 'Revoke admin' : 'Make admin'}
                      </button>
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
