import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/session';

export async function GET(req: NextRequest) {
    // get new refresh time
    const { searchParams } = new URL(req.url);
    const shouldRefresh = searchParams.get('should-refresh');
    const nextUrl = searchParams.get('next');

    const session = await getSession();

    // guard against missing user
    if (!session.user?.identifier) {
        return NextResponse.redirect(new URL('/', req.url));
    }

    // update shouldRefresh time
    session.user = { 
      identifier: session.user?.identifier ?? '',
      shouldRefresh: shouldRefresh ? Number(shouldRefresh) : 0
    };

    await session.save();

    // redirect to home page
    return NextResponse.redirect(new URL(nextUrl || '/', req.url));
}