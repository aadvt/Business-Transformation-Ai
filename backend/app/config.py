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

    # --- Future integrations (unused in this phase) ---
    database_url: str = ""
    watsonx_api_key: str = ""
    watsonx_project_id: str = ""
    guardian_api_url: str = ""
    supermemory_api_key: str = ""
    verification_api_key: str = ""
    orchestrate_api_key: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
