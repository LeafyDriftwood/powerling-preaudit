import { NextRequest, NextResponse } from 'next/server';
import { unsealData } from 'iron-session';
import { SessionData } from '@/lib/session';

// paths that should be accessible without authentication
const PUBLIC_PATHS = ['/auth/callback', '/auth/refresh'];

// middleware to check authentication for protected routes
export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // allow access to public paths 
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // obtain powerling cookie and decrypt 
  const cookieValue = req.cookies.get('powerling-session')?.value;
  if (cookieValue) {
    const session = await unsealData<SessionData>(cookieValue, {
      password: process.env.SESSION_SECRET!,
    });
    
    // check if identifier is present, and then allow access
    if (session.user) {
      // redirect to refresh page if shouldRefresh time has passed
      if (session.user.shouldRefresh < Date.now() / 1000) {
        const next = encodeURIComponent(req.url);
        const refreshCallback = encodeURIComponent(`${process.env.NEXT_PUBLIC_APP_URL}/auth/refresh?next=${next}`);
        return NextResponse.redirect(`https://${process.env.SSO_HOST}/refresh-token?redirect=${refreshCallback}`);
      }
      // continue as normal
      return NextResponse.next();
    } 
  }

  // redirect to sso login if not authenticated
  const callbackUrl = encodeURIComponent(`${process.env.NEXT_PUBLIC_APP_URL}/auth/callback`);
  return NextResponse.redirect(
    `https://${process.env.SSO_HOST}/login?redirect=${callbackUrl}&host=${process.env.APP_HOST}`
  );
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
