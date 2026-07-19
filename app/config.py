from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/server_tracker"
    secret_key: str = "dev-secret-change-me"
    env: str = "development"
    upload_dir: str = "/data/uploads"
    max_upload_size_bytes: int = 250 * 1024 * 1024  # 250 MB, per user request


settings = Settings()
