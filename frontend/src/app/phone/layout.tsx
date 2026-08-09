import type { ReactNode } from "react";

// No AppShell here on purpose — this route is projected in a second browser
// window as "the owner's phone" (a WhatsApp mock, see D4), so it must look
// like a phone, not like a page of our app. Sibling to app/(dashboard) rather
// than inside it, so it never picks up the sidebar/header chrome.
export default function PhoneLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div className="flex h-[780px] w-[390px] flex-col overflow-hidden rounded-[2.5rem] border border-line-strong bg-surface shadow-2xl">
        {children}
      </div>
    </div>
  );
}
