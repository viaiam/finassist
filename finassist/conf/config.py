"""融知客服配置：从项目根目录 .env 或同名环境变量读取。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """必填项缺失时启动失败，避免在首次业务请求中才暴露配置错误。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / '.env',
        env_file_encoding='utf-8',
        env_prefix='FINASSIST_',
        extra='ignore',
    )

    LLM_MODEL: str
    llm_api_key: str
    llm_base_url: str
    database_url: str
    business_api_base_url: str
    app_host: str = '127.0.0.1'
    app_port: int = 18082


settings = Settings()
