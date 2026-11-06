from pydantic_settings import BaseSettings, SettingsConfigDict

# Дефолт только для локальной разработки; в .env всегда свой секрет (>= 32 байт).
# Приложение предупреждает в лог при старте с этим значением.
DEFAULT_JWT_SECRET = "dev-only-secret-change-me-in-env-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://anifolder:anifolder@localhost:5432/anifolder"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Авторизация: access-токен JWT живёт 15 минут, refresh-токен 30 дней
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl: int = 900
    refresh_token_ttl: int = 2_592_000

    redis_url: str = "redis://localhost:6379/0"

    # Фронтенд в dev: Vite — 5173 порт
    cors_origins: str = "http://localhost:5173"


settings = Settings()
