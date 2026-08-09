"use client";

// D5b folded the call view into /command as a full-screen mode — this route
// is now recovery-only, for a stale bookmark or a deep link typed by hand.
// It never renders its own UI.

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Spinner from "@/components/ui/Spinner";

function CallRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const id = searchParams.get("id") ?? searchParams.get("d");
    router.replace(id ? `/command?d=${id}&mode=call` : "/command?mode=call");
  }, [router, searchParams]);

  return (
    <div className="flex h-[50vh] items-center justify-center">
      <Spinner size={18} label="Redirecting to Command…" />
    </div>
  );
}

export default function CallPage() {
  return (
    <Suspense fallback={null}>
      <CallRedirect />
    </Suspense>
  );
}
