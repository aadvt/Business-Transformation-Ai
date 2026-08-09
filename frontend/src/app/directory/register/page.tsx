"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useRegisterVendor } from "@/lib/queries";
import { ApiError } from "@/lib/api";
import { validateGstin } from "@/lib/gstin";

const LANGUAGES: { code: string; label: string }[] = [
  { code: "hi", label: "Hindi" },
  { code: "mr", label: "Marathi" },
  { code: "en", label: "English" },
  { code: "ta", label: "Tamil" },
  { code: "te", label: "Telugu" },
  { code: "gu", label: "Gujarati" },
];

const PINCODE_RE = /^[1-9][0-9]{5}$/;
const PHONE_RE = /^\+91-[0-9]{5}-[0-9]{5}$/;

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[13px] font-medium text-slate-700">{label}</label>
      {children}
      {hint && <p className="mt-1 text-[11.5px] text-slate-400">{hint}</p>}
    </div>
  );
}

const inputClass =
  "w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 outline-none focus:border-slate-400";

export default function RegisterVendorPage() {
  const router = useRouter();
  const register = useRegisterVendor();

  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [gstin, setGstin] = useState("");
  const [udyam, setUdyam] = useState("");
  const [phone, setPhone] = useState("+91-");
  const [languages, setLanguages] = useState<string[]>([]);
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [pincode, setPincode] = useState("");
  const [capacity, setCapacity] = useState("");
  const [leadTime, setLeadTime] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  const gstinCheck = gstin ? validateGstin(gstin) : null;
  const pincodeValid = pincode === "" || PINCODE_RE.test(pincode);
  const phoneValid = phone === "+91-" || PHONE_RE.test(phone);

  const formValid =
    name.trim().length > 1 &&
    category.trim().length > 1 &&
    gstinCheck?.valid === true &&
    PHONE_RE.test(phone) &&
    languages.length > 0 &&
    city.trim().length > 1 &&
    state.trim().length > 1 &&
    PINCODE_RE.test(pincode) &&
    Number(capacity) > 0 &&
    Number(leadTime) > 0;

  function toggleLanguage(code: string) {
    setLanguages((prev) => (prev.includes(code) ? prev.filter((l) => l !== code) : [...prev, code]));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    setSubmitError(null);
    if (!formValid) return;

    register.mutate(
      {
        name: name.trim(),
        category: category.trim(),
        gstin: gstin.trim().toUpperCase(),
        udyam_number: udyam.trim() || undefined,
        phone,
        languages,
        city: city.trim(),
        state: state.trim(),
        pincode,
        capacity_units_per_month: Number(capacity),
        lead_time_days: Number(leadTime),
      },
      {
        onSuccess: (res) => router.push(`/directory/${res.vendor.id}`),
        onError: (err) => setSubmitError(err instanceof ApiError ? err.message : "Registration failed. Please try again."),
      }
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-[20px] font-semibold tracking-tight text-slate-900">List your business</h1>
      <p className="mb-6 text-[13.5px] text-slate-500">
        Free to list. We check your GSTIN structure and checksum, and your Udyam number if you have one, before
        marking you verified — usually instantly.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-5">
        {submitError && (
          <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-[13px] text-red-700">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span>{submitError}</span>
          </div>
        )}

        <Field label="Business name">
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
        </Field>

        <Field label="Category" hint="e.g. Automotive Fasteners, CNC Machined Parts">
          <input value={category} onChange={(e) => setCategory(e.target.value)} className={inputClass} />
        </Field>

        <Field label="GSTIN">
          <input
            value={gstin}
            onChange={(e) => setGstin(e.target.value.toUpperCase())}
            placeholder="27AABCS1429B1ZP"
            maxLength={15}
            className={`${inputClass} font-mono ${gstinCheck && !gstinCheck.valid ? "border-red-300" : gstinCheck?.valid ? "border-emerald-300" : ""}`}
          />
          {gstinCheck && !gstinCheck.valid && (
            <p className="mt-1 flex items-center gap-1 text-[11.5px] text-red-600">
              <AlertTriangle size={11} /> {gstinCheck.reason}
            </p>
          )}
          {gstinCheck?.valid && (
            <p className="mt-1 flex items-center gap-1 text-[11.5px] text-emerald-600">
              <CheckCircle2 size={11} /> Structure and checksum valid
            </p>
          )}
        </Field>

        <Field label="Udyam number (optional)" hint="UDYAM-XX-YY-NNNNNNN">
          <input value={udyam} onChange={(e) => setUdyam(e.target.value.toUpperCase())} className={`${inputClass} font-mono`} />
        </Field>

        <Field label="Phone" hint="+91-XXXXX-XXXXX">
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className={`${inputClass} font-mono ${touched && !phoneValid ? "border-red-300" : ""}`}
          />
          {touched && !phoneValid && <p className="mt-1 text-[11.5px] text-red-600">Expected format +91-XXXXX-XXXXX</p>}
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="City">
            <input value={city} onChange={(e) => setCity(e.target.value)} className={inputClass} />
          </Field>
          <Field label="State">
            <input value={state} onChange={(e) => setState(e.target.value)} className={inputClass} />
          </Field>
        </div>

        <Field label="Pincode">
          <input
            value={pincode}
            onChange={(e) => setPincode(e.target.value.replace(/\D/g, ""))}
            maxLength={6}
            className={`${inputClass} ${touched && !pincodeValid ? "border-red-300" : ""}`}
          />
          {touched && !pincodeValid && <p className="mt-1 text-[11.5px] text-red-600">6-digit pincode required</p>}
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Capacity (units/month)">
            <input type="number" min={1} value={capacity} onChange={(e) => setCapacity(e.target.value)} className={inputClass} />
          </Field>
          <Field label="Lead time (days)">
            <input type="number" min={1} value={leadTime} onChange={(e) => setLeadTime(e.target.value)} className={inputClass} />
          </Field>
        </div>

        <Field label="Languages">
          <div className="flex flex-wrap gap-1.5">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                type="button"
                onClick={() => toggleLanguage(l.code)}
                className={`rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
                  languages.includes(l.code)
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-400"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
          {touched && languages.length === 0 && <p className="mt-1 text-[11.5px] text-red-600">Pick at least one language</p>}
        </Field>

        <button
          type="submit"
          disabled={register.isPending}
          className="w-full rounded-md bg-slate-900 py-2.5 text-[13.5px] font-medium text-white transition-colors hover:bg-slate-700 disabled:opacity-50"
        >
          {register.isPending ? "Registering…" : "Register & verify"}
        </button>
      </form>
    </div>
  );
}
