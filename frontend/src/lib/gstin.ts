// Client-side mirror of backend/app/services/gstin.py's offline structural +
// checksum validation (mod-36 Luhn-like algorithm), so the D2 register form
// can show a real, specific rejection reason in NEXT_PUBLIC_USE_FIXTURES
// mode instead of faking success. Kept in exact algorithmic lockstep with
// the backend on purpose — if that file's checksum logic ever changes,
// this one needs the matching change too.

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const STRUCTURE_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export interface GstinCheck {
  valid: boolean;
  structureValid: boolean;
  checksumValid: boolean;
  stateCode: string | null;
  reason: string | null;
}

function checksumChar(first14: string): string {
  let factor = 1;
  let total = 0;
  for (const ch of first14) {
    const digit = ALPHABET.indexOf(ch);
    factor = factor === 1 ? 2 : 1;
    const product = digit * factor;
    total += Math.floor(product / 36) + (product % 36);
  }
  const checkValue = (36 - (total % 36)) % 36;
  return ALPHABET[checkValue];
}

export function validateGstin(raw: string): GstinCheck {
  const gstin = (raw || "").trim().toUpperCase();

  if (!STRUCTURE_RE.test(gstin)) {
    return {
      valid: false,
      structureValid: false,
      checksumValid: false,
      stateCode: null,
      reason: "Does not match GSTIN structure: 2-digit state code + 10-char PAN + entity code + 'Z' + checksum",
    };
  }

  const expected = checksumChar(gstin.slice(0, 14));
  if (expected !== gstin[14]) {
    return {
      valid: false,
      structureValid: true,
      checksumValid: false,
      stateCode: gstin.slice(0, 2),
      reason: `Checksum mismatch: expected '${expected}', got '${gstin[14]}'`,
    };
  }

  return { valid: true, structureValid: true, checksumValid: true, stateCode: gstin.slice(0, 2), reason: null };
}

// A subset of real GST state codes — enough to demo "state code resolved"
// without shipping the full 37-entry table.
export const GST_STATE_CODES: Record<string, string> = {
  "06": "Haryana",
  "07": "Delhi",
  "08": "Rajasthan",
  "09": "Uttar Pradesh",
  "23": "Madhya Pradesh",
  "24": "Gujarat",
  "27": "Maharashtra",
  "29": "Karnataka",
  "33": "Tamil Nadu",
  "36": "Telangana",
};

export function resolveStateCode(code: string | null): string | null {
  if (!code) return null;
  return GST_STATE_CODES[code] ?? null;
}
