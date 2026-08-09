import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/lib/providers";
import { Inter, Manrope } from "next/font/google";
import { cn } from "@/lib/utils";

// Soft Logic pairs Manrope (headings — geometric, a little warmth at display
// sizes) with Inter (everything functional). globals.css reads both through
// --font-manrope / --font-inter.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });

export const metadata: Metadata = {
  title: "SANJEEVANI — Supply Chain Command",
  description: "Self-healing supply chain: sense, diagnose, source, negotiate, and settle disruptions autonomously.",
};

// AppShell (sidebar/header chrome) lives in app/(dashboard)/layout.tsx, not
// here — /phone must render without it (it's projected as "the owner's
// phone" in a second window), so the root layout stays chrome-free and only
// owns providers.
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={cn("font-sans", inter.variable, manrope.variable)}>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
