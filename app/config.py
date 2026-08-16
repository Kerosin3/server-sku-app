from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/server_tracker"
    secret_key: str = "dev-secret-change-me"
    env: str = "development"
    upload_dir: str = "/data/uploads"
    max_upload_size_bytes: int = 250 * 1024 * 1024  # 250 MB, per user request

    # JSON API for machine consumers (app/routers/api_v1.py). Disabled
    # while api_token is empty — no token, no API, so a deployment that
    # doesn't want one is safe by default. See app/api_auth.py for why
    # this is an interim mechanism and what replaces it.
    api_token: str = ""
    api_service_username: str = "api"  # existing user the API acts as; its role decides what the API may do


settings = Settings()
