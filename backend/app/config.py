from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    access_token_minutes: int = 60 * 24 * 7
    cookie_secure: bool = False
    upload_dir: str = "/data/uploads"
    max_upload_mb: int = 5
    allow_registration: bool = True
    serve_media: bool = False  # dev: отдавать /media из API (в проде — nginx)


settings = Settings()
