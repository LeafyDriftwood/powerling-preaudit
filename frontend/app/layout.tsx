import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from 'react-hot-toast';
import Link from 'next/link';
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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased pt-14`}>
        <nav className="fixed top-0 left-0 right-0 z-50 h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6">
          <Link href="/" className="text-orange-600 font-bold text-lg hover:text-orange-700 transition">
            Powerling Pre-Audit
          </Link>
          <div className="flex items-center gap-4">
            <Link href="/audits" className="text-gray-600 hover:text-gray-900 font-medium transition">
              All Audits
            </Link>
            <Link
              href="/"
              className="bg-orange-500 text-white rounded-full px-4 py-1.5 text-sm font-semibold hover:bg-orange-600 transition"
            >
              New Audit
            </Link>
          </div>
        </nav>
        {children}
        <Toaster />
      </body>
    </html>
  );
}
