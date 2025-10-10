from datetime import timedelta
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    log_level: str = 'INFO'
    app_config_dir: Path = Path('conf').absolute()

    port: int = 8000
    root_path: str = '/'

    computation_queue_time: Optional[float] = timedelta(minutes=30).total_seconds()
    computation_time_limit: Optional[float] = None

    disable_swagger: bool = False
    disable_caching: bool = False

    model_config = SettingsConfigDict(env_file='.env.gateway')
