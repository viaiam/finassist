"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:action 需要的数据模型 + Action 基类
          ActionCall   封装"要调哪个 action"（FlowExecutor 从 yaml 的 action 字段拿）
          ActionResult 封装"调完更新哪些槽位"（FlowExecutor 负责写回 active.slots）
          Action       所有具体 action 的父类：公共 name + 抽象 run
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from finassist.domain.state import DialogueState


# 封装传递 action 属性值（目前只有 name，将来要传参可以在这里加 args）
@dataclass
class ActionCall:
    action_name: str


# 封装 action 远程调用结果：只有"要更新哪些槽位"，不直接改 state
@dataclass
class ActionResult:
    slots_update: dict[str, Any] = field(default_factory=dict)


# Action 基类
class Action(ABC):
    # 公共属性：必须和 yaml 里 action 步骤的 action 字段一模一样
    name: str = ""

    # 抽象方法：具体 action 自己去调中台
    @abstractmethod
    async def run(self, state: DialogueState) -> ActionResult:
        pass
