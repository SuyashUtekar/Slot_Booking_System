from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    admin_token: str
    event_name: str = "Venue Visit Registration"
    event_timezone: str = "Asia/Kolkata"
    max_guests_per_registration: int = 15
    default_slot_start_time: str = "10:00"
    default_slot_end_time: str = "18:00"
    default_slot_capacity: int = 150
    default_slot_date: str = ""
    export_path: str = "./exports/registrations.xlsx"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()

