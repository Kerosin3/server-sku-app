from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/server_tracker"
    secret_key: str = "dev-secret-change-me"
    env: str = "development"
    upload_dir: str = "/data/uploads"
    max_upload_size_bytes: int = 250 * 1024 * 1024  # 250 MB, per user request

    # NOTE: the JSON API (app/routers/api_v1.py) has no settings here on
    # purpose. Its tokens live in the api_tokens table, issued at
    # /api-tokens, so enabling the API, changing what it may do and
    # revoking one consumer are all things an admin does in the interface
    # rather than by editing .env and restarting. API_TOKEN and
    # API_SERVICE_USERNAME are no longer read; leftover values in .env are
    # ignored and can be deleted.


settings = Settings()
