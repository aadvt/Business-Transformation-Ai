"use client";

import dynamic from "next/dynamic";
import { useRef, useState } from "react";
import { FileSpreadsheet, MessageSquare, Paperclip, Send, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";

const NetworkMap = dynamic(() => import("@/components/NetworkMap"), {
  ssr: false,
  loading: () => <div className="panel flex h-full items-center justify-center text-[14px] text-ink-muted">Loading supply network…</div>,
});

type ChatMessage = { from: "system" | "you"; text: string };

function AssistantPanel() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { from: "system", text: "I’m monitoring the supply network. Ask about a vendor, disruption, or shipment." },
  ]);
  const [fileName, setFileName] = useState<string | null>(null);

  function send() {
    const input = inputRef.current;
    const text = input?.value.trim();
    if (!text || !input) return;
    setMessages((current) => [...current, { from: "you", text }, { from: "system", text: "I’ve added that to the operations queue and will surface related network changes here." }]);
    input.value = "";
  }

  return (
    <aside className="panel-flush flex min-h-0 flex-col">
      <div className="border-b border-line px-4 py-4">
        <div className="flex items-center justify-between">
          <div><p className="text-[15px] font-semibold text-ink">Operations assistant</p><p className="mt-0.5 text-[12px] text-ink-muted">Network-aware workspace</p></div>
          <MessageSquare size={16} className="text-accent" />
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((message, index) => <div key={index} className={message.from === "you" ? "ml-8 rounded-md bg-accent px-3 py-2 text-[13px] text-accent-ink" : "mr-4 rounded-md bg-surface-2 px-3 py-2 text-[13px] leading-relaxed text-ink-muted"}>{message.text}</div>)}
      </div>
      <label className="mx-4 mb-3 flex cursor-pointer items-center gap-3 rounded-md border border-dashed border-line-strong bg-surface-2 px-3 py-3 transition-colors hover:border-accent hover:bg-surface-3">
        <UploadCloud size={18} className="text-accent" />
        <span className="min-w-0 flex-1"><span className="block text-[13px] font-medium text-ink">Drop Excel or CSV here</span><span className="block truncate text-[11px] text-ink-muted">{fileName ?? "Supplier lists, shipments, or invoice extracts"}</span></span>
        <FileSpreadsheet size={16} className="text-ink-faint" />
        <input className="sr-only" type="file" accept=".xlsx,.xls,.csv" onChange={(event) => setFileName(event.target.files?.[0]?.name ?? null)} />
      </label>
      <div className="flex gap-2 border-t border-line p-3"><Button size="icon" variant="ghost" icon={<Paperclip size={15} />} /><input ref={inputRef} onKeyDown={(event) => event.key === "Enter" && send()} className="min-w-0 flex-1 bg-transparent px-1 text-[13px] text-ink outline-none placeholder:text-ink-faint" placeholder="Ask about the network…" /><Button size="icon" onClick={send} icon={<Send size={15} />} /></div>
    </aside>
  );
}

export default function OperationsWorkspace() {
  return <div className="grid h-[calc(100vh-170px)] min-h-[680px] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]"><section className="relative min-h-[520px]"><NetworkMap /><div className="pointer-events-none absolute top-4 right-4 rounded-md border border-line bg-surface/95 px-3 py-2 text-[12px] text-ink-muted"><span className="mr-2 inline-block h-2 w-2 rounded-full bg-success" />Live delivery network</div></section><AssistantPanel /></div>;
}
