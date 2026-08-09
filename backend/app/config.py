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
    # Off by default now that real Neon data is wired in: the scripted
    # replay loop (app/mocks/scripted_replay.py) references the old
    # fixture-backed Store shape directly (store.disruptions[...]) and
    # would crash on its first tick against the trimmed Store — and even
    # fixed, broadcasting a fake disruption alongside real DB-backed ones
    # would be actively misleading. Still available for local UI-only work
    # with no DB configured.
    mock_live_replay: bool = False

    # --- Database ---
    # Neon Postgres. Pooled endpoint (PgBouncer, transaction mode) — see
    # app/db.py for the prepared-statement caveat that comes with that.
    database_url: str = ""
    # The one real `organisations` row this whole backend currently scopes
    # to — no multi-tenant auth in this phase, just a fixed scope constant.
    org_id: str = "b2f6c8a0-0000-4000-8000-000000000001"

    # --- Future integrations (unused in this phase) ---
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    guardian_api_url: str = ""
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
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
