import type { Metadata } from "next";
import "@carbon/styles/css/styles.css";
import "./globals.css";
import { SanjeevaniProvider } from "@/lib/store";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: "SANJEEVANI — Supply Chain Command",
  description: "Self-healing supply chain: sense, diagnose, source, negotiate, and settle disruptions autonomously.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <SanjeevaniProvider>
          <AppShell>{children}</AppShell>
        </SanjeevaniProvider>
      </body>
    </html>
  );
}
