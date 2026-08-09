// Mock data for D2's public vendor directory + candidate rail, used while
// the backend's /api/v1/public/vendors endpoints are still being built.
// Same NEXT_PUBLIC_USE_FIXTURES gate as demoFixtures.ts (see api.ts).

import { resolveStateCode, validateGstin } from "./gstin";
import type { PublicVendorDetail, PublicVendorList, SourcingCandidate, VendorRegistrationRequest, VerificationEvidence } from "./types";

function evidence(overrides: Partial<VerificationEvidence> = {}): VerificationEvidence {
  return {
    gstin_structure_valid: true,
    gstin_checksum_valid: true,
    state_code: "27",
    state_code_resolved: true,
    udyam_format_valid: true,
    source: "GSTN + Udyam registry cross-check",
    checked_at: "2026-08-09T06:00:00+00:00",
    ...overrides,
  };
}

export const publicVendorsFixture: PublicVendorList = {
  total: 4,
  items: [
    {
      id: "4c34118b-bbe1-4016-885d-e6bc7917b3b0",
      name: "Shree Balaji Auto Components",
      category: "Automotive Fasteners",
      city: "Pune",
      state: "Maharashtra",
      pincode: "411001",
      distance_km: 12.4,
      lead_time_days: 2,
      capacity_units_per_month: 180000,
      reliability_score_0_100: 82,
      languages: ["hi", "mr", "en"],
      verified: true,
      gstin_masked: "27AAB••••••1ZP",
    },
    {
      id: "1799a38c-a9ed-4d03-b666-4784d6346a7b",
      name: "Kohinoor Precision Pvt Ltd",
      category: "CNC Machined Parts",
      city: "Pune",
      state: "Maharashtra",
      pincode: "411019",
      distance_km: 18.1,
      lead_time_days: 3,
      capacity_units_per_month: 95000,
      reliability_score_0_100: 91,
      languages: ["mr", "en"],
      verified: true,
      gstin_masked: "27AAC••••••1Z9",
    },
    {
      id: "6e2d0a5b-6f0e-4c1a-9c34-6b1a2f0e9d21",
      name: "Marudhar Steel Traders",
      category: "Raw Steel Coil",
      city: "Jodhpur",
      state: "Rajasthan",
      pincode: "342001",
      distance_km: 612.7,
      lead_time_days: 6,
      capacity_units_per_month: 40000,
      reliability_score_0_100: 74,
      languages: ["hi", "en"],
      verified: true,
      gstin_masked: "08AAD••••••2Z4",
    },
    {
      id: "8f5a1c40-2b71-4e9a-9d3a-0c7e5b6f2a11",
      name: "Nandini Fabrication Works",
      category: "Automotive Fasteners",
      city: "Aurangabad",
      state: "Maharashtra",
      pincode: "431001",
      distance_km: 210.5,
      lead_time_days: 5,
      capacity_units_per_month: 22000,
      reliability_score_0_100: 58,
      languages: ["mr"],
      verified: false,
      gstin_masked: "27AAE••••••9Z1",
    },
  ],
};

export const publicVendorDetailFixtures: Record<string, PublicVendorDetail> = Object.fromEntries(
  publicVendorsFixture.items.map((vendor) => [
    vendor.id,
    {
      ...vendor,
      orders_completed: vendor.verified ? Math.round(vendor.reliability_score_0_100 * 3.4) : 0,
      reliability: {
        score_0_100: vendor.reliability_score_0_100,
        on_time_rate: Math.min(0.99, vendor.reliability_score_0_100 / 100 + 0.06),
        orders_completed: vendor.verified ? Math.round(vendor.reliability_score_0_100 * 3.4) : 0,
        disputes: vendor.verified ? Math.max(0, Math.round((100 - vendor.reliability_score_0_100) / 25)) : 0,
      },
      verification: vendor.verified
        ? evidence()
        : evidence({
            gstin_checksum_valid: false,
            state_code_resolved: false,
            source: "GSTN cross-check — pending re-verification",
          }),
    },
  ])
);

// GSTINs/phones already "on file" — so a demo can deliberately trigger a
// duplicate rejection. These are checksum-VALID GSTINs (required — checksum
// is checked before duplication, so an invalid one could never reach the
// duplicate check). Note backend/app/mocks/fixtures/vendors.json's
// "27AABCS1429B1ZP" is NOT checksum-valid under the real mod-36 algorithm
// (verified by hand: expects '7', fixture has 'P') — it predates the
// checksum validator, so it isn't reused here.
const TAKEN_GSTINS = new Set(["27AABCS1429B1Z7", "27AACCK4567D1ZE"]);
const TAKEN_PHONES = new Set(["+91-98230-11223", "+91-98220-44556"]);

// In-memory registry for vendors registered during this session in fixture
// mode — lets /directory/register's "register live, see it listed and
// verified immediately" promise actually work without a backend.
const registeredVendors: PublicVendorDetail[] = [];

export function allPublicVendors(): PublicVendorDetail[] {
  return [...Object.values(publicVendorDetailFixtures), ...registeredVendors];
}

export function findPublicVendor(id: string): PublicVendorDetail | undefined {
  return allPublicVendors().find((v) => v.id === id);
}

function maskGstin(gstin: string): string {
  return `${gstin.slice(0, 5)}••••••${gstin.slice(11)}`;
}

export type RegisterResult = { ok: true; vendor: PublicVendorDetail } | { ok: false; reason: string };

export function registerFixtureVendor(body: VendorRegistrationRequest): RegisterResult {
  const gstin = body.gstin.trim().toUpperCase();
  const check = validateGstin(gstin);
  if (!check.valid) return { ok: false, reason: check.reason ?? "Invalid GSTIN." };

  if (TAKEN_GSTINS.has(gstin) || registeredVendors.some((v) => v.gstin_masked === maskGstin(gstin))) {
    return { ok: false, reason: `A vendor with GSTIN ${gstin} is already registered.` };
  }
  if (TAKEN_PHONES.has(body.phone)) {
    return { ok: false, reason: `A vendor with phone number ${body.phone} is already registered.` };
  }

  const vendor: PublicVendorDetail = {
    id: crypto.randomUUID(),
    name: body.name,
    category: body.category,
    city: body.city,
    state: body.state,
    pincode: body.pincode,
    distance_km: null,
    lead_time_days: body.lead_time_days,
    capacity_units_per_month: body.capacity_units_per_month,
    reliability_score_0_100: 50, // no track record yet — a fresh registration starts neutral
    languages: body.languages,
    verified: true, // checksum + structure passed, so it clears verification immediately
    gstin_masked: maskGstin(gstin),
    orders_completed: 0,
    reliability: { score_0_100: 50, on_time_rate: 0, orders_completed: 0, disputes: 0 },
    verification: {
      gstin_structure_valid: true,
      gstin_checksum_valid: true,
      state_code: check.stateCode,
      state_code_resolved: resolveStateCode(check.stateCode) !== null,
      udyam_format_valid: Boolean(body.udyam_number),
      source: "GSTN + Udyam registry cross-check",
      checked_at: new Date().toISOString(),
    },
  };

  registeredVendors.push(vendor);
  return { ok: true, vendor };
}

export const candidatesFixture: SourcingCandidate[] = [
  {
    vendor_id: "1799a38c-a9ed-4d03-b666-4784d6346a7b",
    name: "Kohinoor Precision Pvt Ltd",
    match_score: 0.91,
    quoted_lead_time_days: 3,
    quoted_unit_price_paise: 1490,
    distance_km: 18.1,
    reliability_score_0_100: 91,
    languages: ["mr", "en"],
    price_delta_pct: 2.8,
    score_components: { reliability: 0.91, lead_time: 0.82, price: 0.71, geography: 0.88, relationship: 0.6 },
    verification: {
      status: "VERIFIED",
      gstin_status: "VERIFIED",
      udyam_status: "VERIFIED",
      checked_at: "2026-08-09T06:00:00+00:00",
      source: "GSTN + Udyam registry cross-check",
    },
  },
  {
    vendor_id: "8f5a1c40-2b71-4e9a-9d3a-0c7e5b6f2a11",
    name: "Nandini Fabrication Works",
    match_score: 0.68,
    quoted_lead_time_days: 5,
    quoted_unit_price_paise: 1380,
    distance_km: 210.5,
    reliability_score_0_100: 58,
    languages: ["mr"],
    price_delta_pct: -4.8,
    score_components: { reliability: 0.58, lead_time: 0.51, price: 0.83, geography: 0.42, relationship: 0.2 },
    verification: {
      status: "UNVERIFIED",
      gstin_status: "FAILED",
      udyam_status: "UNAVAILABLE",
      checked_at: "2026-08-09T06:00:00+00:00",
      source: "GSTN cross-check — pending re-verification",
    },
  },
  {
    vendor_id: "6e2d0a5b-6f0e-4c1a-9c34-6b1a2f0e9d21",
    name: "Marudhar Steel Traders",
    match_score: 0.54,
    quoted_lead_time_days: 6,
    quoted_unit_price_paise: 1450,
    distance_km: 612.7,
    reliability_score_0_100: 74,
    languages: ["hi", "en"],
    price_delta_pct: 0,
    score_components: { reliability: 0.74, lead_time: 0.35, price: 0.6, geography: 0.15, relationship: 0.45 },
    verification: {
      status: "VERIFIED",
      gstin_status: "VERIFIED",
      udyam_status: "VERIFIED",
      checked_at: "2026-08-09T06:00:00+00:00",
      source: "GSTN + Udyam registry cross-check",
    },
  },
];
