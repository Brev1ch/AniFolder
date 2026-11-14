"""Настройки ML-сервиса; окружение имеет приоритет над dotenv-файлами."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ML_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ML_DIR.parent / "backend" / ".env", ML_DIR / ".env"),
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://anifolder:anifolder@localhost:5432/anifolder"
    ml_anilist_data_dir: Path | None = None
    ml_artifact_dir: Path = ML_DIR / "artifacts" / "service"
