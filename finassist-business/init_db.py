"""显式初始化融知业务中台的数据表；不灌入样例数据。"""
from pathlib import Path

from dotenv import load_dotenv

# 必须先加载环境变量，再导入创建引擎的模块。
load_dotenv(Path(__file__).resolve().parent / '.env')
from app.database import engine
from app.models import Base


if __name__ == '__main__':
    Base.metadata.create_all(engine)
    print('融知中台表结构初始化完成（不含样例数据）')
