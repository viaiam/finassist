"""
repository/orm/dialogue_state.py —— 唯一的一张表：dialogue_states

■ 表结构
    sender_id    VARCHAR(128)  主键    用户唯一标识
    state_json   TEXT          非空    整个 DialogueState 序列化后的 JSON

■ 为什么只有两列
    ※ 见 repository/dialogue_repository.py 里「为什么整棵树存一列」的说明：
      状态的访问模式是「整体读、整体写」，拆表只会增加复杂度。

■ 字段类型选择的理由
    · sender_id 用 String(128)：够放 uuid / 手机号 / 平台用户 id，且能做主键索引；
    · state_json 用 Text：MySQL 的 TEXT 上限 64KB，够存几百轮对话；
      如果聊天记录很长，可以换成 LONGTEXT 或改成只存最近 N 轮。

■ 注意
    Mapped[...] / mapped_column(...) 是 SQLAlchemy 2.0 的新写法（带类型标注），
    比老式 Column(...) 更好用：IDE 能提示，mypy 能查。
"""
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from finassist.repository.orm.base import Base


class DialogueStateRecord(Base):
    __tablename__ = 'dialogue_states'
    # 类属性和表字段对应关系
    sender_id:Mapped[str] = mapped_column(String(255),primary_key=True)
    state_json:Mapped[str] = mapped_column(Text,nullable=False)