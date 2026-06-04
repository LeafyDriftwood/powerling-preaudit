import { SignJWT } from 'jose';

// encode secret
const secret = new TextEncoder().encode(process.env.JWT_SECRET!);

// sign the identifier 
export async function signUserJwt(identifier: string): Promise<string> {
  return new SignJWT({ identifier })
    .setProtectedHeader({ alg: 'HS256' })
    .setExpirationTime('1h')
    .sign(secret);
}
