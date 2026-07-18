from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/server_tracker"
    secret_key: str = "dev-secret-change-me"
    env: str = "development"


settings = Settings()
