import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/session';

// destroy session cookie and redirect to sso logout
export async function GET(req: NextRequest) {
  const session = await getSession();
  session.destroy();

  return NextResponse.redirect(
    `https://${process.env.SSO_HOST}/logout`
  );
}
