import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/session';

export async function GET(req: NextRequest) {
  // extract token param from this url
  const { searchParams } = new URL(req.url);
  const token = searchParams.get('token');
  const shouldRefresh = searchParams.get('should-refresh');

  // error if token is not present 
  if (!token) {
    return NextResponse.redirect(new URL('/', req.url));
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
      return NextResponse.redirect(new URL('/', req.url));
    }

    // extract user identifer
    const userData = await ssoRes.json();
    const identifier = userData.identifier;

    // redirect to homepage if identifer is not present
    if (!identifier) {
      return NextResponse.redirect(new URL('/', req.url));
    }

    // set cookie with identifer 
    const session = await getSession();
    session.user = { 
      identifier,
      shouldRefresh: shouldRefresh ? Number(shouldRefresh) : 0
    };

    await session.save();

    // redirect to home page
    return NextResponse.redirect(new URL('/', req.url));
  } catch {
    return NextResponse.redirect(new URL('/', req.url));
  }
}
