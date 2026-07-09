'use server';

import { getSession } from '@/lib/session';
import { signUserJwt } from '@/lib/jwt';

// get jwt from user info
async function getAuthHeader() {
  const session = await getSession();
  const jwt = await signUserJwt(session.user!.identifier);
  return { Authorization: `Bearer ${jwt}` };
}

// check response status before parsing JSON to avoid SyntaxError on non-JSON error bodies
async function parseJsonOrThrow(response: Response, fallbackMessage: string) {
  if (!response.ok) {
    let detail = fallbackMessage;
    try { detail = (await response.json()).detail || fallbackMessage; } catch {}
    throw new Error(detail);
  }
  return response.json();
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
  return parseJsonOrThrow(response, 'Failed to create audit job.');
}

// list all audit jobs
export async function listAudits() {
  // get headers, call api
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits`, { headers });

  // handle response
  return parseJsonOrThrow(response, 'Failed to fetch audit jobs.');
}

// get details of an audit job
export async function getAuditDetails(job_id: string) {
  // get headers, call api and handle response
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}`, { headers });

  return parseJsonOrThrow(response, 'Failed to fetch audit details.');
}

// get result of an audit job
export async function getAuditResult(job_id: string) {
  // get headers, call api and handle response
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}/result`, { headers });

  return parseJsonOrThrow(response, 'Failed to fetch audit result.');
}

// retry an audit job
export async function retryAudit(job_id: string) {
  // get headers, call api
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}/retry`, {
    method: 'POST',
    headers: headers,
  });

  // handle response
  return parseJsonOrThrow(response, 'Failed to retry audit job.');
}

// return the current user
export async function getCurrentUser() {
  const session = await getSession();
  return session.user?.identifier ?? null;
}

// get all the users (should only be accessible to admins)
export async function getAllUsers() {
  // get headers, call api
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users`, { headers });

  // handle response
  return parseJsonOrThrow(response, 'Failed to fetch users.');
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
  return parseJsonOrThrow(response, 'Failed to update user role.');
}

// get a specific user and their audits (admin only)
export async function getUser(email: string) {
  // get headers, call api and handle response
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/${encodeURIComponent(email)}`, { headers });
  return parseJsonOrThrow(response, 'Failed to fetch user.');
}

// get the pdf report for an audit job — returns raw bytes (URL.createObjectURL must be called client-side)
export async function getAuditPdf(job_id: string): Promise<Uint8Array> {
  const headers = await getAuthHeader();
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/audits/${job_id}/pdf`, { headers });
  if (!response.ok) throw new Error('Failed to fetch audit PDF.');
  return new Uint8Array(await response.arrayBuffer());
}