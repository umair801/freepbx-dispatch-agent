from pydantic_settings import BaseSettings
from pydantic import Field
from enum import Enum
from functools import lru_cache


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    # App
    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    gemini_model: str = "gemini-2.5-flash"

    # Google Gemini
    gemini_api_key: str = Field(..., env="GEMINI_API_KEY")

    # Supabase
    supabase_url: str = Field(..., env="SUPABASE_URL")
    supabase_key: str = Field(..., env="SUPABASE_KEY")

    # Asterisk AMI (NEW in AgAI-33 -- replaces Twilio Voice as the call source)
    asterisk_ami_host: str = Field(default="127.0.0.1", env="ASTERISK_AMI_HOST")
    asterisk_ami_port: int = Field(default=5038, env="ASTERISK_AMI_PORT")
    asterisk_ami_username: str = Field(default="", env="ASTERISK_AMI_USERNAME")
    asterisk_ami_secret: str = Field(default="", env="ASTERISK_AMI_SECRET")
    asterisk_ari_base_url: str = Field(default="http://127.0.0.1:8088/ari", env="ASTERISK_ARI_BASE_URL")
    asterisk_ari_username: str = Field(default="", env="ASTERISK_ARI_USERNAME")
    asterisk_ari_secret: str = Field(default="", env="ASTERISK_ARI_SECRET")
    asterisk_ari_app_name: str = Field(default="agai33_dispatch", env="ASTERISK_ARI_APP_NAME")

    # Twilio (kept for SMS dispatch notifications to technicians -- NOT used for
    # inbound voice in AgAI-33; Asterisk/AMI replaces that role)
    twilio_account_sid: str = Field(default="", env="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", env="TWILIO_AUTH_TOKEN")
    twilio_phone_number: str = Field(default="", env="TWILIO_PHONE_NUMBER")

    # SendGrid
    sendgrid_api_key: str = Field(..., env="SENDGRID_API_KEY")
    from_email: str = Field(..., env="FROM_EMAIL")

    # Google Geocoding (NEW in AgAI-33 -- resolves customer address to lat/lng
    # for technician proximity ranking; reuses the same Google Cloud project
    # as GOOGLE_API_KEY used elsewhere in the portfolio)
    google_api_key: str = Field(default="", env="GOOGLE_API_KEY")

    # ElevenLabs (NEW in AgAI-33 -- TTS/STT bridge for Asterisk calls, see
    # notifications/voice_bridge.py)
    elevenlabs_api_key: str = Field(default="", env="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(default="pNInz6obpgDQGcFmaJgB", env="ELEVENLABS_VOICE_ID")

    # Dispatch policy (NEW in AgAI-33 -- replaces booking policy)
    max_alternative_technicians: int = 3
    dispatch_proximity_weight: float = 0.6   # weight given to proximity vs queue depth in ranking
    dispatch_queue_weight: float = 0.4
    technician_max_queue_depth: int = 5      # jobs before a technician is deprioritized

    model_config = {"env_file": ".env", "case_sensitive": False}


# This line must exist -- it creates the singleton instance
settings = Settings()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
