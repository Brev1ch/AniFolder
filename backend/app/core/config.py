from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://anifolder:anifolder@localhost:5432/anifolder"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 10


settings = Settings()
