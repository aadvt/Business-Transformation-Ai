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

    # --- Transaction agent bridge ---
    # Settlement execute hands the batch off to the transaction-agent service
    # (../transaction-agent) as a best-effort side call — see
    # app/transaction_agent_client.py. Runs on its own port since it's a
    # separate FastAPI app from this one.
    transaction_agent_base_url: str = "http://127.0.0.1:8001"
    transaction_agent_api_key: str = "dev-local-key"

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
