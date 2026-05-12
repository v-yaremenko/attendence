from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    admin_key: str = "changeme"
    secret_key: str = "dev-secret-change-me"
    google_spreadsheet_id: str = ""
    google_service_account_json: str = "credentials/service_account.json"
    google_oauth_client_json: str = "credentials/oauth_client.json"
    course_name: str = "OOP"
    ngrok_auth_token: str = ""
    ngrok_domain: str = ""


settings = Settings()
