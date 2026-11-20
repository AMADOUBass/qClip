import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Unbounded } from "next/font/google";
import { Suspense } from "react";

import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/sidebar";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const unbounded = Unbounded({ subsets: ["latin"], variable: "--font-unbounded", weight: ["600", "700", "800"], display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: "qClip",
  description: "Clips verticaux sous-titrés à partir des VOD de tes campagnes — 100 % local.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={`${inter.variable} ${unbounded.variable} ${jetbrains.variable} antialiased`}>
      <body className="min-h-screen">
        <Providers>
          {/* Suspense : la barre latérale et les pages lisent l'URL (usePathname, useParams…) ; Next 16 veut ces
              lectures sous un Suspense pour pouvoir pré-rendre le reste. */}
          <div className="flex min-h-screen">
            <Suspense fallback={<aside className="w-[104px] shrink-0 border-r border-line bg-surface" />}>
              <Sidebar />
            </Suspense>
            <main className="min-w-0 flex-1 px-10 py-8">
              <Suspense fallback={<div className="card-qc h-96 animate-pulse" />}>{children}</Suspense>
            </main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
