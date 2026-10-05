from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = DEFAULT_OPENAI_MODEL
    DATABASE_URL: str = "sqlite:///./rcm_demo.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
