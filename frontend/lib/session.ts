import { getIronSession } from 'iron-session';
import { SessionOptions } from 'iron-session';
import { cookies } from 'next/headers';

// type definition for json response from cookie
export interface SessionData {
  user?: {
    identifier: string;
    role: string;
    shouldRefresh: number;
  };

}

// iron-session options to be passed to the session handler
export const sessionOptions: SessionOptions = {
  password: process.env.SESSION_SECRET!,
  cookieName: 'powerling-session',
  cookieOptions: {
    secure: process.env.NODE_ENV === 'production',
    httpOnly: true,
    sameSite: 'lax',
  },
};

// decrypt the cookie and returns session data in the form of SessionData
export async function getSession() {
  return getIronSession<SessionData>(await cookies(), sessionOptions);
}
