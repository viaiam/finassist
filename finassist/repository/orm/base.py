"""
repository/orm/base.py —— SQLAlchemy 2.0 声明式基类

■ 它是什么
    只定义一个 Base。所有 ORM 模型继承它，SQLAlchemy 靠这份继承关系
    收集「这个应用有哪些表」，create_all / 元数据都从这里出发。

■ 为什么单独一个文件
    ※ 防止循环导入：模型文件要 import Base，Base 又不能 import 模型。
      分成两个文件后，依赖是单向的 base ← dialogue_state。

■ 用法
    建表：await conn.run_sync(Base.metadata.create_all)  （见 utils/db.py::init_db_engine）
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass