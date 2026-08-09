"use client";

import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Boxes,
  Building2,
  CalendarClock,
  Check,
  CloudUpload,
  FileSpreadsheet,
  Loader2,
  Tags,
  WifiOff,
} from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import PageHeader, { EmptyState, SectionHeading } from "@/components/PageHeader";
import StatTile from "@/components/StatTile";
import TileGrid from "@/components/ui/TileGrid";
import Badge from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Skeleton from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useLiveEvents, useLiveFeed } from "@/lib/live";
import {
  queryKeys,
  useBusinessProfile,
  useBusinessQuestions,
  useIngestFiles,
  useSaveBusinessAnswers,
} from "@/lib/queries";
import {
  INGEST_STAGE_ORDER,
  type BusinessProfile,
  type BusinessQuestion,
  type IngestQueuedFile,
  type IngestStage,
  type IngestStatus,
  type WSEventPayloads,
  type WSEventType,
} from "@/lib/types";

// Module-level so the array identity is stable across renders — useLiveEvents
// memoises on it, and a fresh literal each render would re-filter the whole
// buffer on every state change this page makes (which is a lot, mid-parse).
const INGEST_EVENTS: WSEventType[] = ["INGEST_PROGRESS"];

// Mirrors api.ts's own resolution so the failure copy can name the exact host
// the browser tried, rather than a guess.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const ACCEPTED_EXTENSIONS = [".xlsx", ".xls", ".csv"];

const STAGE_LABEL: Record<IngestStage, string> = {
  PARSING_STARTED: "Opened",
  SHEETS_FOUND: "Sheets",
  ROWS_FOUND: "Rows",
  ENTITIES_FOUND: "Entities",
  DEDUPE_COMPLETE: "Deduped",
  FAILED: "Failed",
};

// The parser's four known workbook shapes plus its honest "I don't recognise
// this" verdict — backend/app/services/ingest/parser.py's HEADER_TOKENS.
const CLASSIFICATION_LABEL: Record<string, string> = {
  vendor_master: "Vendor master",
  purchase_log: "Purchase log",
  inventory: "Inventory",
  rate_card: "Rate card",
  unknown: "Unrecognised",
};

function classificationLabel(raw: string | undefined): string {
  if (!raw) return "—";
  return CLASSIFICATION_LABEL[raw] ?? raw.replace(/_/g, " ");
}

type StepId = 1 | 2 | 3;

interface SheetFinding {
  sheet: string;
  classification?: string;
  confidence?: number;
  row_count?: number;
  entity_count?: number;
}

interface FileProgress {
  file_id: string;
  name: string;
  stages: IngestStage[];
  sheet_count?: number;
  sheets: SheetFinding[];
  parser?: string;
  status?: IngestStatus;
  error?: string;
}

type QueuedFile = IngestQueuedFile & { ingest_id: string };

/** Highest position reached in the five-stage happy path; -1 before anything. */
function reachedIndex(progress: FileProgress | undefined): number {
  if (!progress) return -1;
  let max = -1;
  for (const stage of progress.stages) {
    const index = INGEST_STAGE_ORDER.indexOf(stage);
    if (index > max) max = index;
  }
  return max;
}

function upsertSheet(sheets: SheetFinding[], name: string, patch: Partial<SheetFinding>): SheetFinding[] {
  const index = sheets.findIndex((s) => s.sheet === name);
  if (index === -1) return [...sheets, { sheet: name, ...patch }];
  const next = [...sheets];
  next[index] = { ...next[index], ...patch };
  return next;
}

function applyEvent(existing: FileProgress | undefined, payload: WSEventPayloads["INGEST_PROGRESS"]): FileProgress {
  const base: FileProgress = existing ?? { file_id: payload.file_id, name: payload.name, stages: [], sheets: [] };
  const next: FileProgress = {
    ...base,
    name: payload.name || base.name,
    stages: base.stages.includes(payload.stage) ? base.stages : [...base.stages, payload.stage],
  };

  switch (payload.stage) {
    case "SHEETS_FOUND":
      next.sheet_count = payload.sheet_count;
      break;
    case "ROWS_FOUND":
      if (payload.sheet)
        next.sheets = upsertSheet(base.sheets, payload.sheet, {
          classification: payload.classification,
          confidence: payload.confidence,
          row_count: payload.row_count,
        });
      break;
    case "ENTITIES_FOUND":
      if (payload.sheet) next.sheets = upsertSheet(base.sheets, payload.sheet, { entity_count: payload.entity_count });
      break;
    case "DEDUPE_COMPLETE":
      next.parser = payload.parser;
      next.status = payload.status ?? "COMPLETED";
      break;
    case "FAILED":
      next.status = "FAILED";
      next.error = payload.error || "The parser failed without reporting a reason.";
      break;
    default:
      break;
  }
  return next;
}

/* ---------------------------------- step rail --------------------------------- */

interface StepDef {
  id: StepId;
  label: string;
  hint: string;
}

const STEPS: StepDef[] = [
  { id: 1, label: "Drop your data", hint: "Excel or CSV workbooks" },
  { id: 2, label: "Watch it parse", hint: "Sheets, classes, row counts" },
  { id: 3, label: "Business profile", hint: "Four questions, then the picture" },
];

function StepRail({
  active,
  complete,
  live,
  onSelect,
}: {
  active: StepId;
  complete: Record<StepId, boolean>;
  live: boolean;
  onSelect: (step: StepId) => void;
}) {
  return (
    <nav aria-label="Onboarding steps" className="panel-flush mb-6 grid grid-cols-1 sm:grid-cols-3">
      {STEPS.map((step) => {
        const isActive = step.id === active;
        const isComplete = complete[step.id];
        const isLive = step.id === 2 && live;
        return (
          <button
            key={step.id}
            type="button"
            onClick={() => onSelect(step.id)}
            aria-current={isActive ? "step" : undefined}
            className={clsx(
              "relative flex cursor-pointer items-center gap-3 px-4 py-3.5 text-left outline-offset-[-2px] transition-colors duration-200",
              "border-line not-first:border-t sm:not-first:border-t-0 sm:not-first:border-l",
              isActive ? "bg-surface-2" : "hover:bg-surface-2/60"
            )}
          >
            {isActive && <span className="absolute inset-x-0 top-0 h-[2px] bg-accent" />}
            <span
              className={clsx(
                "numeric flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                isComplete
                  ? "bg-success-dim text-success"
                  : isActive
                    ? "bg-accent text-accent-ink"
                    : "bg-surface-3 text-ink-faint"
              )}
            >
              {isComplete ? <Check size={13} /> : step.id}
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className={clsx("text-[13px] font-semibold", isActive ? "text-ink" : "text-ink-muted")}>
                  {step.label}
                </span>
                {isLive && <span className="animate-blink size-1.5 rounded-full bg-accent" />}
              </span>
              <span className="mt-0.5 block truncate text-[11px] text-ink-faint">{step.hint}</span>
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/* ------------------------------- step 1: dropzone ------------------------------ */

function DropZone({
  onFiles,
  uploading,
  uploadingCount,
  compact,
}: {
  onFiles: (files: File[]) => void;
  uploading: boolean;
  uploadingCount: number;
  compact: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  // dragenter/dragleave fire for every child element crossed, so a boolean
  // flickers off the moment the pointer moves over the icon. Depth-count it.
  const depthRef = useRef(0);

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      depthRef.current = 0;
      setDragging(false);
      onFiles([...event.dataTransfer.files]);
    },
    [onFiles]
  );

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        depthRef.current += 1;
        setDragging(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        depthRef.current -= 1;
        if (depthRef.current <= 0) {
          depthRef.current = 0;
          setDragging(false);
        }
      }}
      onDrop={handleDrop}
      className={clsx(
        "flex flex-col items-center justify-center rounded-xl border-2 border-dashed text-center transition-colors duration-200",
        compact ? "gap-2 px-6 py-8" : "gap-3 px-6 py-14",
        dragging ? "border-accent bg-accent-dim/50" : "border-line-strong bg-surface-2/40"
      )}
    >
      <span
        className={clsx(
          "flex items-center justify-center rounded-full transition-colors duration-200",
          compact ? "size-10" : "size-14",
          dragging ? "bg-accent text-accent-ink" : "bg-surface-3 text-ink-faint"
        )}
      >
        {uploading ? (
          <Loader2 size={compact ? 18 : 24} className="animate-spin" />
        ) : (
          <CloudUpload size={compact ? 18 : 24} />
        )}
      </span>

      <p className={clsx("font-display font-bold tracking-[-0.01em] text-ink", compact ? "text-[15px]" : "text-[19px]")}>
        {uploading
          ? `Uploading ${uploadingCount} file${uploadingCount === 1 ? "" : "s"}…`
          : dragging
            ? "Release to upload"
            : compact
              ? "Add more workbooks"
              : "Drop your workbooks here"}
      </p>

      <p className="max-w-md text-[12.5px] leading-relaxed text-ink-muted">
        Vendor masters, purchase logs, inventory extracts, rate cards — whatever you already keep. Excel
        (.xlsx, .xls) or CSV, several at a time.
      </p>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(",")}
        hidden
        onChange={(e) => {
          onFiles([...(e.target.files ?? [])]);
          e.target.value = ""; // so re-picking the same file fires change again
        }}
      />
      <Button
        size="sm"
        variant={compact ? "secondary" : "default"}
        className="mt-1"
        disabled={uploading}
        onClick={() => inputRef.current?.click()}
      >
        Browse files
      </Button>
    </div>
  );
}

function UploadError({ error, onDismiss }: { error: unknown; onDismiss: () => void }) {
  const isApi = error instanceof ApiError;
  return (
    <div className="mt-4 rounded-lg border border-critical/30 bg-critical-dim/50 px-4 py-3.5">
      <div className="flex items-start gap-2.5">
        <AlertTriangle size={15} className="mt-0.5 shrink-0 text-critical" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-critical">
            {isApi ? `The API rejected the upload (${error.status})` : "Couldn't reach the backend"}
          </p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
            {isApi ? (
              <>
                <span className="numeric">{API_BASE_URL}</span> answered, but not with a success:{" "}
                {error.message}. Nothing was parsed — check the API logs, then drop the files again.
              </>
            ) : (
              <>
                The upload never left this browser — nothing at <span className="numeric">{API_BASE_URL}</span>{" "}
                answered. Start the Sanjeevani API on that address and drop the files again. No progress is being
                faked here in the meantime.
              </>
            )}
          </p>
          <Button variant="secondary" size="sm" className="mt-2.5" onClick={onDismiss}>
            Dismiss
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------ step 2: parse feed ----------------------------- */

function ConfidenceMeter({ value }: { value: number | undefined }) {
  if (value === undefined) return <span className="text-[11.5px] text-ink-faint">—</span>;
  const pct = Math.round(value * 100);
  const tone = value >= 0.66 ? "bg-success" : value >= 0.34 ? "bg-accent" : value > 0 ? "bg-warning" : "bg-line-strong";
  return (
    <span className="flex items-center gap-2">
      <span
        role="img"
        aria-label={`Classification confidence ${pct} percent`}
        className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-surface-3"
      >
        <span
          className={clsx("block h-full rounded-full transition-[width] duration-500 ease-out", tone)}
          style={{ width: `${Math.max(pct, 3)}%` }}
        />
      </span>
      <span className="numeric text-[11.5px] text-ink-muted">{pct}%</span>
    </span>
  );
}

function StageChecklist({ progress }: { progress: FileProgress | undefined }) {
  const reached = reachedIndex(progress);
  const failed = progress?.status === "FAILED";
  const totalRows = progress?.sheets.reduce((sum, s) => sum + (s.row_count ?? 0), 0) ?? 0;
  const totalEntities = progress?.sheets.reduce((sum, s) => sum + (s.entity_count ?? 0), 0) ?? 0;

  function detailFor(stage: IngestStage): string | null {
    if (!progress) return null;
    switch (stage) {
      case "SHEETS_FOUND":
        return progress.sheet_count !== undefined ? String(progress.sheet_count) : null;
      case "ROWS_FOUND":
        return totalRows > 0 ? totalRows.toLocaleString("en-IN") : null;
      case "ENTITIES_FOUND":
        return totalEntities > 0 ? totalEntities.toLocaleString("en-IN") : null;
      case "DEDUPE_COMPLETE":
        return progress.parser ?? null;
      default:
        return null;
    }
  }

  return (
    <ol className="flex flex-wrap items-start gap-x-1 gap-y-2">
      {INGEST_STAGE_ORDER.map((stage, index) => {
        const done = index <= reached;
        const current = !failed && index === reached && reached < INGEST_STAGE_ORDER.length - 1;
        const stopped = failed && index > reached;
        const detail = detailFor(stage);
        return (
          <li key={stage} className="flex items-center gap-1">
            <span
              className={clsx(
                "flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium transition-colors duration-300",
                done && !current && "bg-success-dim text-success",
                current && "bg-accent-dim text-accent",
                !done && !stopped && "bg-surface-2 text-ink-faint",
                stopped && "bg-surface-2 text-ink-faint opacity-50"
              )}
            >
              <span
                className={clsx(
                  "size-1.5 shrink-0 rounded-full",
                  done && !current && "bg-success",
                  current && "animate-blink bg-accent",
                  !done && "bg-line-strong"
                )}
              />
              {STAGE_LABEL[stage]}
              {detail && <span className="numeric font-semibold">{detail}</span>}
            </span>
            {index < INGEST_STAGE_ORDER.length - 1 && (
              <span className={clsx("h-px w-3", index < reached ? "bg-success/40" : "bg-line")} />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function FileParseCard({ file, progress }: { file: QueuedFile; progress: FileProgress | undefined }) {
  const failed = progress?.status === "FAILED";
  const completed = progress?.status === "COMPLETED";
  const started = progress !== undefined;
  const sheets = progress?.sheets ?? [];

  return (
    <article className="panel-flush">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <span
          className={clsx(
            "flex size-8 shrink-0 items-center justify-center rounded-md",
            failed ? "bg-critical-dim text-critical" : completed ? "bg-success-dim text-success" : "bg-surface-3 text-ink-faint"
          )}
        >
          <FileSpreadsheet size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13.5px] font-semibold text-ink">{progress?.name ?? file.name}</p>
          <p className="numeric mt-0.5 truncate text-[11px] text-ink-faint">{file.file_id.slice(0, 8)}</p>
        </div>
        <Badge tone={failed ? "alert" : completed ? "positive" : started ? "accent" : "idle"}>
          {failed ? "Failed" : completed ? "Parsed" : started ? "Parsing" : "Queued"}
        </Badge>
      </header>

      <div className="border-t border-line px-4 py-3">
        <StageChecklist progress={progress} />
      </div>

      {failed && (
        <div className="border-t border-critical/25 bg-critical-dim/40 px-4 py-3">
          <p className="flex items-center gap-1.5 text-[12px] font-semibold text-critical">
            <AlertTriangle size={13} />
            The parser could not read this file
          </p>
          <p className="numeric mt-1.5 break-words text-[11.5px] leading-relaxed text-ink-muted">{progress?.error}</p>
        </div>
      )}

      {sheets.length > 0 && (
        <div className="border-t border-line">
          <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto_auto_auto] items-center gap-x-4 px-4 pt-3 pb-1.5">
            <span className="eyebrow">Sheet</span>
            <span className="eyebrow">Classified as</span>
            <span className="eyebrow">Confidence</span>
            <span className="eyebrow text-right">Rows</span>
            {/* Both columns come off the wire separately, but today's parser
                derives entity_count from the same row list, so they read the
                same. Kept distinct because the backend reports them
                separately and resolution is what will make them diverge. */}
            <span className="eyebrow text-right">Entities</span>
          </div>
          {sheets.map((sheet) => (
            <div
              key={sheet.sheet}
              className="row-hover grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto_auto_auto] items-center gap-x-4 border-t border-line px-4 py-2"
            >
              <span className="truncate text-[12.5px] font-medium text-ink">{sheet.sheet}</span>
              <span
                className={clsx(
                  "truncate text-[12.5px]",
                  sheet.classification === "unknown" ? "text-ink-faint italic" : "text-ink-muted"
                )}
              >
                {classificationLabel(sheet.classification)}
              </span>
              <ConfidenceMeter value={sheet.confidence} />
              <span className="numeric text-right text-[12.5px] text-ink">
                {sheet.row_count !== undefined ? sheet.row_count.toLocaleString("en-IN") : "—"}
              </span>
              <span className="numeric text-right text-[12.5px] text-ink">
                {sheet.entity_count !== undefined ? sheet.entity_count.toLocaleString("en-IN") : "—"}
              </span>
            </div>
          ))}
        </div>
      )}

      {completed && (
        <footer className="border-t border-line px-4 py-2 text-[11px] text-ink-faint">
          Read by <span className="numeric">{progress?.parser ?? "the workbook parser"}</span> — every figure above
          came out of this file, not a fixture.
        </footer>
      )}
    </article>
  );
}

/* ---------------------------- step 3: business profile -------------------------- */

function QuestionPicker({
  question,
  value,
  onChange,
}: {
  question: BusinessQuestion;
  value: string | undefined;
  onChange: (value: string) => void;
}) {
  const labelId = useId();
  return (
    <div className="rounded-lg border border-line bg-surface-2/40 px-3.5 py-3">
      <p id={labelId} className="text-[13px] font-medium text-ink">
        {question.question}
      </p>
      <div role="radiogroup" aria-labelledby={labelId} className="mt-2.5 flex flex-wrap gap-1.5">
        {question.options.map((option) => {
          const selected = value === option;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(option)}
              className={clsx(
                "cursor-pointer rounded-full border px-3 py-1.5 text-[12px] font-medium outline-offset-2 transition-colors duration-200",
                selected
                  ? "border-accent bg-accent text-accent-ink shadow-panel"
                  : "border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink"
              )}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ChipRow({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span key={value} className="rounded-full bg-surface-3 px-2.5 py-1 text-[11.5px] font-medium text-ink-muted">
            {value}
          </span>
        ))}
      </div>
    </div>
  );
}

function ProfilePayoff({ profile }: { profile: BusinessProfile }) {
  const hasData = profile.vendor_count > 0 || profile.item_count > 0;

  if (!hasData) {
    return (
      <EmptyState>
        Nothing in the workspace to profile yet. Drop a workbook in step one and this fills in with the vendors and
        items it finds.
      </EmptyState>
    );
  }

  return (
    <div className="panel px-5 py-5">
      <TileGrid minWidth={180}>
        <StatTile label="Vendors" value={profile.vendor_count.toLocaleString("en-IN")} icon={Building2} />
        <StatTile label="Distinct items" value={profile.item_count.toLocaleString("en-IN")} icon={Boxes} />
        <StatTile label="Categories" value={profile.categories.length.toLocaleString("en-IN")} icon={Tags} />
        <StatTile
          label="Avg payment cycle"
          value={`${profile.avg_payment_cycle_days} d`}
          icon={CalendarClock}
        />
      </TileGrid>

      <div className="space-y-4">
        <ChipRow label="Categories you buy in" values={profile.categories} />
        <ChipRow label="Peak season" values={profile.peak_months ?? []} />
        <ChipRow label="Plant locations" values={profile.plant_locations} />
        <ChipRow label="Top dependencies" values={profile.top_dependencies} />
      </div>

      <p className="mt-5 border-t border-line pt-3 text-[11px] leading-relaxed text-ink-faint">
        Recomputed from the vendor and purchase-order records in your workspace every time this page loads — not a
        stored summary, and not a sample.
      </p>
    </div>
  );
}

/* ------------------------------------- page ------------------------------------ */

export default function OnboardingPage() {
  const queryClient = useQueryClient();
  const { connectionState } = useLiveFeed();
  const events = useLiveEvents(INGEST_EVENTS);

  const ingest = useIngestFiles();
  const questionsQuery = useBusinessQuestions();
  const profileQuery = useBusinessProfile();
  const saveAnswers = useSaveBusinessAnswers();

  const [chosenStep, setChosenStep] = useState<StepId | null>(null);
  const [queued, setQueued] = useState<QueuedFile[]>([]);
  const [progress, setProgress] = useState<Record<string, FileProgress>>({});
  const [rejected, setRejected] = useState<string[]>([]);
  const [editedAnswers, setEditedAnswers] = useState<Record<string, string>>({});

  const seenEventsRef = useRef<Set<string>>(new Set());

  const profile = profileQuery.data;
  const questions = questionsQuery.data ?? [];
  const hasProfileData = (profile?.vendor_count ?? 0) > 0 || (profile?.item_count ?? 0) > 0;

  // Landing on a workspace that already has data should open on the payoff, not
  // on an empty dropzone. Derived rather than synced into state by an effect, so
  // an explicit click (which sets `chosenStep`) always wins from then on.
  const profileSettled = profileQuery.isSuccess || profileQuery.isError;
  const step: StepId = chosenStep ?? (profileSettled && hasProfileData ? 3 : 1);

  // Saved answers are the base layer; local picks overlay them. After a
  // successful save the refetched profile catches up and the overlay becomes a
  // no-op, which is what makes the dirty check below settle back to clean.
  const savedAnswers = profile?.answers ?? {};
  const answers: Record<string, string> = { ...savedAnswers, ...editedAnswers };

  // Fold the raw event stream into per-file state rather than deriving it on
  // every render: useLiveEvents' buffer is capped, so a large multi-sheet drop
  // would otherwise start losing its own early stages off the top.
  useEffect(() => {
    const fresh = events.filter((event) => !seenEventsRef.current.has(event.event_id));
    if (fresh.length === 0) return;
    fresh.reverse(); // the hook hands back newest-first; apply in arrival order
    for (const event of fresh) seenEventsRef.current.add(event.event_id);

    setProgress((prev) => {
      const next = { ...prev };
      for (const event of fresh) {
        const payload = event.payload as WSEventPayloads["INGEST_PROGRESS"];
        next[payload.file_id] = applyEvent(next[payload.file_id], payload);
      }
      return next;
    });

    if (fresh.some((event) => (event.payload as WSEventPayloads["INGEST_PROGRESS"]).stage === "DEDUPE_COMPLETE")) {
      queryClient.invalidateQueries({ queryKey: queryKeys.businessProfile });
      queryClient.invalidateQueries({ queryKey: ["vendors"] });
    }
  }, [events, queryClient]);

  const handleFiles = useCallback(
    (dropped: File[]) => {
      if (dropped.length === 0) return;
      const accepted = dropped.filter((file) =>
        ACCEPTED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))
      );
      setRejected(dropped.filter((file) => !accepted.includes(file)).map((file) => file.name));
      if (accepted.length === 0) return;

      ingest.mutate(accepted, {
        onSuccess: (response) => {
          setQueued((prev) => [...prev, ...response.files.map((file) => ({ ...file, ingest_id: response.ingest_id }))]);
          setChosenStep(2);
        },
      });
    },
    [ingest]
  );

  const parsingCount = queued.filter((file) => {
    const status = progress[file.file_id]?.status;
    return status !== "COMPLETED" && status !== "FAILED";
  }).length;

  const stepComplete: Record<StepId, boolean> = {
    1: queued.length > 0 || hasProfileData,
    2: queued.length > 0 && parsingCount === 0,
    3: Object.keys(savedAnswers).length > 0,
  };

  const answeredAll = questions.length > 0 && questions.every((question) => Boolean(answers[question.id]));
  const answersDirty = questions.some(
    (question) => (answers[question.id] ?? "") !== (savedAnswers[question.id] ?? "")
  );

  return (
    <div>
      <PageHeader
        title="Data sources"
        subtitle="Sanjeevani cannot warn you about a supply chain it has never seen. Drop the workbooks you already keep, watch the parser read them sheet by sheet, then answer four questions so it knows how your business runs."
      />

      <StepRail active={step} complete={stepComplete} live={parsingCount > 0} onSelect={setChosenStep} />

      {step === 1 && (
        <section aria-labelledby="step-1-heading">
          <SectionHeading>
            <span id="step-1-heading">Drop your data</span>
          </SectionHeading>

          <div className="panel px-5 py-5">
            <DropZone
              onFiles={handleFiles}
              uploading={ingest.isPending}
              uploadingCount={ingest.variables?.length ?? 0}
              compact={hasProfileData || queued.length > 0}
            />

            {rejected.length > 0 && (
              <p className="mt-3 flex items-start gap-2 text-[12px] text-warning">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>
                  Skipped {rejected.length} file{rejected.length === 1 ? "" : "s"} the parser cannot open:{" "}
                  <span className="text-ink-muted">{rejected.join(", ")}</span>. Only .xlsx, .xls and .csv are read.
                </span>
              </p>
            )}

            {ingest.isError && <UploadError error={ingest.error} onDismiss={() => ingest.reset()} />}

            <p className="mt-4 border-t border-line pt-3 text-[12px] leading-relaxed text-ink-muted">
              The file goes straight to the parser — there is no sample workbook standing in for yours. Whatever the
              next step shows you was read out of the bytes you just dropped.
            </p>
          </div>

          {queued.length > 0 && (
            <div className="mt-4">
              <Button variant="secondary" size="sm" onClick={() => setChosenStep(2)}>
                See what the parser found ({queued.length})
              </Button>
            </div>
          )}
        </section>
      )}

      {step === 2 && (
        <section aria-labelledby="step-2-heading">
          <SectionHeading count={queued.length}>
            <span id="step-2-heading">Watch it parse</span>
          </SectionHeading>

          {connectionState !== "open" && (
            <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3">
              <WifiOff size={15} className="mt-0.5 shrink-0 text-warning" />
              <p className="text-[12.5px] leading-relaxed text-ink-muted">
                <span className="font-semibold text-warning">The live feed is down.</span> Files you already uploaded
                are still being read on the server, but their progress cannot stream in until the connection is back.
                Nothing below will move while this warning is showing.
              </p>
            </div>
          )}

          {queued.length === 0 ? (
            <EmptyState>
              Nothing queued in this session. Drop a workbook in step one and each file appears here with its own row,
              advancing as the parser reports back. This view is live-only — a page reload clears it, though anything
              already read stays in your profile.
            </EmptyState>
          ) : (
            <div className="flex flex-col gap-3">
              {queued.map((file) => (
                <FileParseCard key={file.file_id} file={file} progress={progress[file.file_id]} />
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => setChosenStep(1)}>
              Add more files
            </Button>
            <Button size="sm" onClick={() => setChosenStep(3)}>
              Continue to business profile
            </Button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section aria-labelledby="step-3-heading" className="space-y-6">
          <div>
            <SectionHeading count={questions.length || undefined}>
              <span id="step-3-heading">Four questions</span>
            </SectionHeading>

            {questionsQuery.isPending ? (
              <Skeleton className="h-64" />
            ) : questionsQuery.isError ? (
              <div className="rounded-lg border border-critical/30 bg-critical-dim/50 px-4 py-3.5">
                <p className="flex items-center gap-2 text-[13px] font-semibold text-critical">
                  <AlertTriangle size={14} />
                  Couldn&apos;t load the questions
                </p>
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink-muted">
                  Nothing at <span className="numeric">{API_BASE_URL}</span> answered. Start the Sanjeevani API and
                  retry.
                </p>
                <Button variant="secondary" size="sm" className="mt-2.5" onClick={() => questionsQuery.refetch()}>
                  Retry
                </Button>
              </div>
            ) : (
              <div className="panel px-5 py-5">
                <p className="mb-4 text-[12.5px] leading-relaxed text-ink-muted">
                  Your spreadsheets say what you buy. These say how you buy it — the context the agents need before
                  they can judge which disruption actually hurts.
                </p>

                <div className="grid gap-3 lg:grid-cols-2">
                  {questions.map((question) => (
                    <QuestionPicker
                      key={question.id}
                      question={question}
                      value={answers[question.id]}
                      onChange={(value) => setEditedAnswers((prev) => ({ ...prev, [question.id]: value }))}
                    />
                  ))}
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3.5">
                  <Button
                    size="sm"
                    disabled={!answeredAll || !answersDirty || saveAnswers.isPending}
                    onClick={() =>
                      saveAnswers.mutate(answers, {
                        onSuccess: () =>
                          toast.success("Business profile saved", {
                            description: "The agents will weigh disruptions against these answers from now on.",
                          }),
                      })
                    }
                  >
                    {saveAnswers.isPending ? "Saving…" : "Save answers"}
                  </Button>
                  <p className="text-[11.5px] text-ink-faint">
                    {!answeredAll
                      ? `${questions.filter((q) => answers[q.id]).length} of ${questions.length} answered`
                      : answersDirty
                        ? "Unsaved changes"
                        : "Saved"}
                  </p>
                  {saveAnswers.isError && (
                    <p className="text-[11.5px] text-critical">
                      Save failed — the API did not accept the answers. Nothing was stored.
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>

          <div>
            <SectionHeading>What we now know about your business</SectionHeading>
            {profileQuery.isPending ? (
              <Skeleton className="h-52" />
            ) : profileQuery.isError ? (
              <EmptyState>
                The profile endpoint at <span className="numeric">{API_BASE_URL}</span> is not answering, so there is
                nothing honest to show here yet.
              </EmptyState>
            ) : profile ? (
              <ProfilePayoff profile={profile} />
            ) : null}
          </div>
        </section>
      )}
    </div>
  );
}
