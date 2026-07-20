from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    whatsapp_verify_token: str = "autonogrow_verify_token"
    whatsapp_token: str = "replace_me"
    whatsapp_phone_number_id: str = "replace_me"
    whatsapp_api_version: str = "v23.0"
    whatsapp_fake_mode: bool = True

    business_name: str = "AutonoGrow Demo"
    timezone: str = "Europe/Madrid"

    @property
    def WHATSAPP_VERIFY_TOKEN(self) -> str:
        return self.whatsapp_verify_token

    @property
    def WHATSAPP_TOKEN(self) -> str:
        return self.whatsapp_token

    @property
    def WHATSAPP_PHONE_NUMBER_ID(self) -> str:
        return self.whatsapp_phone_number_id

    @property
    def WHATSAPP_API_VERSION(self) -> str:
        return self.whatsapp_api_version

    @property
    def WHATSAPP_FAKE_MODE(self) -> bool:
        return self.whatsapp_fake_mode

    @property
    def BUSINESS_NAME(self) -> str:
        return self.business_name

    @property
    def TIMEZONE(self) -> str:
        return self.timezone


settings = Settings()
