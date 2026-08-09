"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCheck, MoreVertical, Paperclip, Search, Send, ShieldCheck } from "lucide-react";
import { usePhoneMessages, queryKeys, WEB_APPROVER } from "@/lib/queries";
import { api } from "@/lib/api";
import { decideFixtureApproval } from "@/lib/phoneFixtures";
import type { ApprovalDecision, PhoneMessage } from "@/lib/types";

// WhatsApp Web's light-theme colour language, rebuilt in plain CSS — no
// logo/wordmark/brand asset anywhere, and the footer says so explicitly.
// This is the OWNER's phone: "Sanjeevani" (the agent) is the contact,
// AGENT messages render as incoming (left, white), OWNER messages (typed
// here, or the auto-generated confirmation after a tap) render as outgoing
// (right, light green).
const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "true";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function timeLabel(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function TypingBubble() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-lg rounded-tl-sm bg-white px-3 py-2.5 shadow-sm">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#8696a0]"
            style={{ animationDelay: `${i * 120}ms`, animationDuration: "900ms" }}
          />
        ))}
      </div>
    </div>
  );
}

function SystemPill({ text }: { text: string }) {
  return (
    <div className="my-2 flex justify-center">
      <span className="max-w-[85%] rounded-md bg-[#fef9e7] px-2.5 py-1 text-center text-[11px] text-[#8c7a1e] shadow-sm">{text}</span>
    </div>
  );
}

function TextBubble({ message }: { message: PhoneMessage }) {
  const outbound = message.from === "OWNER";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={outbound ? "flex justify-end" : "flex justify-start"}
    >
      <div
        className={`max-w-[78%] rounded-lg px-2.5 py-1.5 text-[14px] leading-[19px] shadow-sm ${
          outbound ? "rounded-tr-sm bg-[#d9fdd3] text-[#111b21]" : "rounded-tl-sm bg-white text-[#111b21]"
        }`}
      >
        <span className="whitespace-pre-line">{message.text}</span>
        <span className="ml-2 inline-flex translate-y-[3px] items-center gap-0.5 text-[10.5px] text-[#667781]">
          {timeLabel(message.at)}
          {outbound && <CheckCheck size={13} className="text-[#53bdeb]" />}
        </span>
      </div>
    </motion.div>
  );
}

function ApprovalCardBubble({
  message,
  sending,
  onDecide,
}: {
  message: PhoneMessage;
  sending: boolean;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  const resolved = message.status && message.status !== "PENDING";

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: "easeOut" }} className="flex justify-start">
      <div className="w-[86%] overflow-hidden rounded-lg rounded-tl-sm bg-white shadow-sm">
        <div className="px-3 pt-2.5 pb-2">
          <p className="mb-1.5 text-[13px] leading-snug font-medium text-[#111b21]">{message.headline}</p>
          <p className="numeric mb-2 text-[22px] leading-none font-semibold text-[#111b21]">{message.exposure_display}</p>
          <ul className="space-y-1">
            {message.plan_summary?.map((line, i) => (
              <li key={i} className="flex gap-1.5 text-[12px] leading-snug text-[#3b4a54]">
                <span className="text-[#54656f]">•</span>
                {line}
              </li>
            ))}
          </ul>
        </div>

        {resolved ? (
          <div className="border-t border-[#e9edef] bg-[#f0f2f5] px-3 py-2 text-center text-[12.5px] font-medium text-[#3b4a54]">
            {message.status === "APPROVED" ? "✓ Approved" : message.status === "OPTIONS_REQUESTED" ? "Options requested" : message.status}
          </div>
        ) : (
          <div className="flex border-t border-[#e9edef]">
            <button
              type="button"
              disabled={sending}
              onClick={() => onDecide("REQUEST_OPTIONS")}
              className="flex-1 border-r border-[#e9edef] py-2.5 text-[13px] font-medium text-[#3b4a54] transition-colors hover:bg-[#f5f6f6] disabled:opacity-50"
            >
              Modify
            </button>
            <button
              type="button"
              disabled={sending}
              onClick={() => onDecide("APPROVE")}
              className="flex-1 py-2.5 text-[13px] font-semibold text-[#008069] transition-colors hover:bg-[#f5f6f6] disabled:opacity-50"
            >
              {sending ? "Sending…" : "Approve"}
            </button>
          </div>
        )}
      </div>
    </motion.div>
  );
}

export default function PhonePage() {
  const { data } = usePhoneMessages();
  const queryClient = useQueryClient();

  const [displayed, setDisplayed] = useState<PhoneMessage[]>([]);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const [sendingApprovalId, setSendingApprovalId] = useState<string | null>(null);

  const seenIds = useRef<Set<string>>(new Set());
  // One idempotency key per approval card, generated once and reused on
  // retry — a double-tap must never submit two different keys.
  const idempotencyKeys = useRef<Record<string, string>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const processingRef = useRef(false);

  // The drain effect below only ever *appends* newly-arrived messages, so an
  // already-displayed message (the approval card, chiefly) needs its own
  // sync — otherwise a status flip from PENDING to APPROVED after a tap
  // would update the underlying data but never reach the stale copy already
  // sitting in `displayed`.
  useEffect(() => {
    if (!data) return;
    setDisplayed((prev) => prev.map((m) => data.items.find((d) => d.id === m.id) ?? m));
  }, [data]);

  useEffect(() => {
    if (!data || processingRef.current) return;
    const incoming = data.items.filter((m) => !seenIds.current.has(m.id));
    if (incoming.length === 0) return;

    processingRef.current = true;
    let cancelled = false;

    async function drain() {
      for (const msg of incoming) {
        if (cancelled) break;
        seenIds.current.add(msg.id);
        if (msg.from === "AGENT" && msg.kind !== "SYSTEM") {
          setTyping(true);
          await sleep(800);
          if (cancelled) break;
          setTyping(false);
        }
        setDisplayed((prev) => [...prev, msg]);
        await sleep(150);
      }
      processingRef.current = false;
    }
    drain();

    return () => {
      cancelled = true;
    };
  }, [data]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayed.length, typing]);

  async function handleDecide(message: PhoneMessage, decision: ApprovalDecision) {
    if (!message.approval_id || sendingApprovalId) return;
    setSendingApprovalId(message.approval_id);

    if (!idempotencyKeys.current[message.approval_id]) {
      idempotencyKeys.current[message.approval_id] = crypto.randomUUID();
    }
    const idempotency_key = idempotencyKeys.current[message.approval_id];

    try {
      if (USE_FIXTURES) {
        decideFixtureApproval(message.approval_id, decision);
      } else {
        await api.decideApproval(message.approval_id, {
          decision,
          channel: "WHATSAPP",
          decided_by: WEB_APPROVER,
          idempotency_key,
        });
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.phoneMessages });
    } finally {
      setSendingApprovalId(null);
    }
  }

  function handleSend() {
    const text = draft.trim();
    if (!text) return;
    setDisplayed((prev) => [
      ...prev,
      { id: `local-${Date.now()}`, kind: "TEXT", from: "OWNER", text, at: new Date().toISOString() },
    ]);
    setDraft("");
  }

  return (
    <div className="flex h-full flex-col bg-[#e5ddd5]">
      <header className="flex h-[60px] shrink-0 items-center gap-3 bg-[#008069] px-3 text-white">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/20">
          <ShieldCheck size={17} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-medium">Sanjeevani</p>
          <p className="truncate text-[12px] text-white/80">online</p>
        </div>
        <Search size={19} className="shrink-0 text-white/85" />
        <MoreVertical size={19} className="shrink-0 text-white/85" />
      </header>

      <div
        className="flex-1 overflow-y-auto px-3 py-3"
        style={{ backgroundImage: "radial-gradient(rgba(0,0,0,0.035) 1px, transparent 1px)", backgroundSize: "16px 16px" }}
      >
        <div className="flex flex-col gap-1.5">
          {displayed.map((m) =>
            m.kind === "SYSTEM" ? (
              <SystemPill key={m.id} text={m.text ?? ""} />
            ) : m.kind === "APPROVAL_CARD" ? (
              <ApprovalCardBubble
                key={m.id}
                message={m}
                sending={sendingApprovalId === m.approval_id}
                onDecide={(decision) => handleDecide(m, decision)}
              />
            ) : (
              <TextBubble key={m.id} message={m} />
            )
          )}
          <AnimatePresence>{typing && <TypingBubble key="typing" />}</AnimatePresence>
          <div ref={bottomRef} />
        </div>
      </div>

      <footer className="flex shrink-0 flex-col bg-[#f0f2f5]">
        <div className="flex items-center gap-2 px-2.5 py-2">
          <Paperclip size={20} className="shrink-0 text-[#54656f]" />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Type a message"
            className="h-9 min-w-0 flex-1 rounded-lg bg-white px-3 text-[14px] text-[#111b21] placeholder:text-[#8696a0] focus:outline-none"
          />
          <button
            onClick={handleSend}
            aria-label="Send"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[#54656f] transition-colors hover:text-[#008069]"
          >
            <Send size={19} />
          </button>
        </div>
        <p className="px-3 pb-1.5 text-center text-[9.5px] text-[#8696a0]">
          Simulated interface for this demo — not affiliated with or sent via WhatsApp.
        </p>
      </footer>
    </div>
  );
}
