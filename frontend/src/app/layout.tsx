import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/lib/providers";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

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
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
