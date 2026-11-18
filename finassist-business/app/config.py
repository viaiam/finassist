"""业务中台配置：独立前缀和数据库，避免与客服进程混用。"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # 中台沿用环境变量读取方式；启动时用 uvicorn --env-file 加载本地配置。
    database_url: str = os.getenv('FINASSIST_BUSINESS_DATABASE_URL',
        'mysql+pymysql://root:change-me@127.0.0.1:3306/finassist_business?charset=utf8mb4')
    app_host: str = os.getenv('FINASSIST_BUSINESS_APP_HOST', '127.0.0.1')
    app_port: int = int(os.getenv('FINASSIST_BUSINESS_APP_PORT', '18081'))


settings = Settings()
