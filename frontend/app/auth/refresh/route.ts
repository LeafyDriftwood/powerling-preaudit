import { NextRequest, NextResponse } from 'next/server';
import { getSession } from '@/lib/session';
import { signUserJwt } from '@/lib/jwt';

export async function GET(req: NextRequest) {
    // get new refresh time
    const { searchParams } = new URL(req.url);
    const shouldRefresh = searchParams.get('should-refresh');
    const nextUrl = searchParams.get('next');

    const session = await getSession();

    // guard against missing user
    if (!session.user?.identifier) {
        return NextResponse.redirect(new URL('/', process.env.NEXT_PUBLIC_APP_URL!));
    }

    // update shouldRefresh time
    session.user = { 
        identifier: session.user?.identifier ?? '',
        role: session.user?.role ?? 'user',
        shouldRefresh: shouldRefresh ? Number(shouldRefresh) : 0
    };

    await session.save();

    // update last_connected_at on token refresh
    try {
        const jwt = await signUserJwt(session.user.identifier);
        await fetch(`${process.env.NEXT_PUBLIC_API_URL}/users/me`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${jwt}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: session.user.role }),
        });
    } catch (e) { console.error('[auth] failed to update last_connected_at on refresh:', e); }

    // redirect to home page
    return NextResponse.redirect(new URL(nextUrl || '/', process.env.NEXT_PUBLIC_APP_URL!));
}