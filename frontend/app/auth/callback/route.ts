import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { signUserJwt } from '@/lib/jwt';

export async function GET(req: NextRequest) {
  // extract token param from this url
  const { searchParams } = new URL(req.url);
  const token = searchParams.get('token');
  const shouldRefresh = searchParams.get('should-refresh');

  // error if token is not present 
  const appUrl = process.env.NEXT_PUBLIC_APP_URL!;

  if (!token) {
    return NextResponse.redirect(new URL('/', appUrl));
  }

  // call sso api using the token
  try {
    const ssoRes = await fetch(
      `https://${process.env.SSO_HOST}/user/${token}`,
      {
        headers: {
          Authorization: `Bearer ${process.env.SSO_SERVICE_KEY}`,
          'Service-Provider': process.env.APP_HOST!,
        },
      }
    );

    // redirect to homepage if sso api call fails
    if (!ssoRes.ok) {
      return NextResponse.redirect(new URL('/', appUrl));
    }

    // extract user identifer
    const userData = await ssoRes.json();
    const identifier = userData.identifier;
    const ssoRole = userData.rights.admin ? 'admin' : 'user';

    // redirect to homepage if identifer is not present
    if (!identifier) {
      return NextResponse.redirect(new URL('/', appUrl));
    }


    // verify role on our backend too
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/me`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${await signUserJwt(identifier)}` },
    });

    // handle response
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Failed to obtain user information.');

    // use admin if our backend says so, otherwise use sso role
    const role = data.role === 'admin' ? 'admin' : ssoRole; 

    // set cookie with identifer 
    const session = await getSession();
    session.user = { 
      identifier,
      role: role,
      shouldRefresh: shouldRefresh ? Number(shouldRefresh) : 0
    };

    await session.save();

    // insert user record in backend
    try {
      const jwt = await signUserJwt(identifier);
      // user by default unless they have the admin right
      await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/me`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${jwt}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
    } catch (e) { console.error('[auth] failed to upsert user record:', e); }

    // redirect to home page
    return NextResponse.redirect(new URL('/', appUrl));
  } catch {
    return NextResponse.redirect(new URL('/', appUrl));
  }
}
