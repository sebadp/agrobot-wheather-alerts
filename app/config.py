from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://agrobot:agrobot@localhost:5432/agrobot"
    EVAL_INTERVAL_MINUTES: int = 15
    DELTA_THRESHOLD: float = 0.10
    COOLDOWN_HOURS: int = 6
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
