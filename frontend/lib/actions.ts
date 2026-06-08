'use server';

import { getSession } from '@/lib/session';
import { signUserJwt } from '@/lib/jwt';

// get jwt from user info
async function getAuthHeader() {
  const session = await getSession();
  const jwt = await signUserJwt(session.user!.identifier);
  return { Authorization: `Bearer ${jwt}` };
}

// create an audit job
export async function createAudit(formData: FormData) {
  // get headers
  const headers = await getAuthHeader();

  // call api
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits`, {
    method: 'POST',
    headers: headers,
    body: formData,
  });

  // handle response
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to create audit job.');
  return data;
}

// list all audit jobs
export async function listAudits() {
  // get headers
  const headers = await getAuthHeader();

  // call api
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits`, {
    headers: headers,
  });

  // handle response
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to fetch audit jobs.');
  return data;
}

// get details of an audit job
export async function getAuditDetails(job_id: string) {
  // get headers
  const headers = await getAuthHeader();

  // call api
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}`, {
    headers: headers,
  });

  // handle response
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to fetch audit details.');
  return data;
}

// get result of an audit job
export async function getAuditResult(job_id: string) {
  // get headers
  const headers = await getAuthHeader();

  // call api
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}/result`, {
    headers: headers,
  });

  // handle response
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to fetch audit result.');
  return data;
}

// return the current user
export async function getCurrentUser() {
  const session = await getSession();
  return session.user?.identifier ?? null;
}

// get all the users (should only be accessible to admins)
export async function getAllUsers() {
  // get headers
  const headers = await getAuthHeader();
  
  // call api
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users`, {
    headers: headers,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to fetch users.');
  return data;
}

// update a user's role (should only be accessible to admins)
export async function updateUserRole(identifier: string, role: string) {
  // get headers
  const headers = await getAuthHeader();

  // call api
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/${identifier}/role`, {
    method: 'PATCH',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });

  // handle response
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to update user role.');
  return data;
}

// get a specific user and their audits (admin only)
export async function getUser(email: string) {
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/${encodeURIComponent(email)}`, { headers });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Failed to fetch user.');
  return data;
}