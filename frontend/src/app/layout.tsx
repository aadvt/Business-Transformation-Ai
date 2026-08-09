import type { Metadata } from "next";
import "./globals.css";
import { AppProviders } from "@/lib/providers";
import AppShell from "@/components/AppShell";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

export const metadata: Metadata = {
  title: "SANJEEVANI — Supply Chain Command",
  description: "Self-healing supply chain: sense, diagnose, source, negotiate, and settle disruptions autonomously.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <body>
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
