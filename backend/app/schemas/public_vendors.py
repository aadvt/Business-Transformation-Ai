"""Public vendor directory schemas — no API key required, rate-limited."""

from pydantic import BaseModel, Field


class VerificationDetail(BaseModel):
    field: str
    status: str  # VALID, INVALID, UNCHECKED
    description: str


class VendorVerification(BaseModel):
    overall_status: str  # VERIFIED | FAILED | UNAVAILABLE | UNVERIFIED
    gstin_status: str
    gstin_masked: str  # first 2 + "..." + last 3 chars
    udyam_status: str | None = None
    details: list[VerificationDetail]
    source: str  # OFFLINE_CHECKSUM, provider name, etc.
    checked_at: str


class PublicVendor(BaseModel):
    id: str
    name: str
    category: str
    city: str
    state: str
    distance_km: float | None = None
    lead_time_days: int
    capacity_hint: str
    price_band: str
    languages: list[str]
    reliability: dict = Field(default_factory=dict)  # score_0_100, on_time_rate, orders_completed
    verification: VendorVerification


class PublicVendorList(BaseModel):
    items: list[PublicVendor]
    total: int


class PublicVendorDetail(PublicVendor):
    pass


class VendorRegistration(BaseModel):
    name: str
    gstin: str
    udyam_number: str | None = None
    category: str
    city: str
    state: str
    pincode: str
    phone: str
    email: str
    languages: list[str]
    capacity_hint: str
    lead_time_days: int
    price_band: str


class RegistrationResponse(BaseModel):
    vendor_id: str
    created: bool
    reason_if_duplicate: str | None = None  # "gstin_exists" | "phone_exists" | "name_city_exists"
    verification: VendorVerification | None = None
