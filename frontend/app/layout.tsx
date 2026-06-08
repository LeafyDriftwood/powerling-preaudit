import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from 'react-hot-toast';
import Link from 'next/link';
import { getSession } from '@/lib/session';
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Powerling Pre-Audit",
  description: "Automated website pre-audit reports",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const session = await getSession();
  const username = session.user?.identifier?.split('@')[0] ?? null;
  const isAdmin = session.user?.role === 'admin';

  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased pt-14`}>
        <nav className="fixed top-0 left-0 right-0 z-50 h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6">
          <Link href="/" className="text-green-800 font-bold text-lg hover:text-green-900 transition">
            Powerling Pre-Audit
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/audits" className="text-gray-600 hover:text-gray-900 font-medium transition">
              All Audits
            </Link>
            {isAdmin && (
              <Link href="/admin/users" className="text-gray-600 hover:text-gray-900 font-medium transition">
                Admin
              </Link>
            )}
            <Link
              href="/"
              className="bg-green-700 text-white rounded-full px-4 py-1.5 text-sm font-semibold hover:bg-green-800 transition"
            >
              New Audit
            </Link>
            {username && (
              <>
                <span className="text-gray-300">|</span>
                <span className="text-sm text-gray-500">{username}</span>
                <a href="/auth/logout" className="text-sm text-green-700 hover:text-green-800 font-semibold transition">
                  Log out
                </a>
              </>
            )}
          </div>
        </nav>
        {children}
        <Toaster />
      </body>
    </html>
  );
}
