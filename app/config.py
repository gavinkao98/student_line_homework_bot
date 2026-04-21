from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    LINE_CHANNEL_SECRET: str = ""

    TEACHER_USER_ID: str = ""
    STUDENT_USER_ID: str = ""

    CRON_SECRET: str = ""
    ASSIGNMENT_PUSH_TIME: str = "19:00"
    REMINDER_TIME: str = "21:00"

    TZ: str = "Asia/Taipei"
    DATABASE_URL: str = "sqlite:///./bot.db"
    PHOTO_DIR: str = "./photos"
    LOG_LEVEL: str = "INFO"

    CARRY_OVER_UNFINISHED: bool = True
    CARRY_OVER_WINDOW_DAYS: int = 7

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TZ)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
