from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Server ---
    app_env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Auth ---
    require_api_key: bool = False
    api_key: str = "changeme-dev-key"

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Mock data behavior ---
    mock_live_replay: bool = True
    # When true, routers read from the in-memory JSON-fixture store (Phase 1
    # behavior) instead of the database. Fallback switch for when Postgres is
    # unreachable (e.g. venue wifi blocks outbound 5432).
    use_mocks: bool = False

    # --- Database (Phase 2) ---
    # Pooled Neon connection (hostname has "-pooler") — used for all app request
    # traffic. Also accepts sqlite:///./sanjeevani.db as an offline fallback.
    database_url: str = "sqlite:///./sanjeevani.db"
    # Direct (non-pooled) Neon connection — used ONLY by create_all/seed scripts.
    # Falls back to database_url when unset (e.g. for sqlite).
    database_url_direct: str = ""

    # --- LLM / watsonx.ai (Phase 3) ---
    # "auto"    -> use watsonx when credentials are present, else stub
    # "watsonx" -> force watsonx (still degrades to stub if a call fails)
    # "stub"    -> never touch the network
    llm_provider: str = "auto"
    watsonx_url: str = "https://eu-de.ml.cloud.ibm.com"
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    watsonx_model_id: str = "ibm/granite-4-h-small"
    watsonx_api_version: str = "2024-05-31"
    watsonx_iam_url: str = "https://iam.cloud.ibm.com/identity/token"
    llm_timeout_seconds: float = 20.0
    llm_max_attempts: int = 3

    # --- Granite Guardian (Phase 3) ---
    guardian_model_id: str = "ibm/granite-guardian-3-8b"
    guardian_enabled: bool = True

    # --- Future integrations (unused in this phase) ---
    supermemory_api_key: str = ""
    verification_api_key: str = ""
    orchestrate_api_key: str = ""

    # --- Agents / orchestrator (Phase 4a) ---
    demo_mode: bool = True  # gates POST /disruptions/simulate — never enable in a real deployment
    sentinel_interval_seconds: int = 30  # background scheduler loop period; generous, this is a demo

    # Sentinel detector thresholds
    overdue_delivery_threshold_days: int = 2
    vendor_silence_threshold_days: int = 10
    quality_spike_lookback_days: int = 30
    quality_spike_multiplier: float = 2.0  # rejection rate must exceed vendor baseline by this factor
    price_shock_threshold_pct: float = 15.0  # quoted price this many % above trailing SKU median

    # Exposure engine
    daily_line_cost_paise: int = 2_000_000_00  # ₹20L/day, matches the Phase 1 narrative example

    # Sourcing scoring weights (must sum to 1.0 — enforced by a test)
    sourcing_weight_reliability: float = 0.35
    sourcing_weight_lead_time: float = 0.25
    sourcing_weight_price: float = 0.20
    sourcing_weight_geography: float = 0.15
    sourcing_weight_relationship: float = 0.05

    # Guardrails — also exposed to the voice agent via GET /vendors/{id}/context
    max_price_uplift_pct: float = 20.0
    max_lead_time_days: int = 10
    requires_human_above_paise: int = 50_000_000_00  # ₹5,00,00,000 — mandatory human review above this exposure

    # --- Impact graph severity tiers (Demo phase D1) ---
    # Tier 1 >= 10L, Tier 2 >= 3L, Tier 3 below — exposed in the response so
    # the UI can show why a disruption landed in a given tier.
    impact_tier1_exposure_paise: int = 10_00_000 * 100  # ₹10L
    impact_tier2_exposure_paise: int = 3_00_000 * 100  # ₹3L

    verification_provider: str = ""  # empty -> offline GSTIN/Udyam checksum only
    verification_provider_url: str = ""
    verification_provider_api_key: str = ""
    verification_timeout_seconds: float = 5.0
    verification_cache_ttl_hours: int = 24

    # --- TTM stockout-risk detector (Phase 4b) ---
    # Instant kill switch if the model misbehaves close to demo time — no
    # redeploy needed, just flip this and restart (or even hot-toggle if we
    # ever expose it as a runtime setting).
    enable_ttm_detector: bool = True
    ttm_model_id: str = "ibm-granite/granite-timeseries-ttm-r2"
    ttm_forecast_horizon: int = 96  # model's native prediction_length
    ttm_context_length: int = 512  # model's native context_length

    # --- Transaction agent bridge ---
    # Settlement execute hands the batch off to the transaction-agent service
    # (../transaction-agent) as a best-effort side call — see
    # app/transaction_agent_client.py. Runs on its own port since it's a
    # separate FastAPI app from this one.
    transaction_agent_base_url: str = "http://127.0.0.1:8001"
    transaction_agent_api_key: str = "dev-local-key"

    # D5a: Bolna context delivery. The CSV path works without these values.
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet_name: str = "Vendors"
    google_service_account_json: str = ""
    bolna_webhook_public_url: str = "https://affecting-gains-thinner.ngrok-free.dev"
    bolna_webhook_secret: str = ""
    webhook_timeout_seconds: int = 120
    llm_record: bool = False
    llm_replay: bool = False
    verification_replay: bool = False
    demo_reveal_speed: str = "1x"

    @property
    def watsonx_configured(self) -> bool:
        return bool(self.watsonx_api_key and self.watsonx_project_id and self.watsonx_url)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def database_url_direct_resolved(self) -> str:
        return self.database_url_direct or self.database_url


settings = Settings()
