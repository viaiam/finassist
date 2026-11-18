"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:action 调用入口。FlowExecutor 的 action 步骤只调这里，
          由它按名字去注册表里找具体 Action，再调 run 拿 ActionResult。
"""
from finassist.domain.state import DialogueState
from finassist.task.action.base import Action, ActionCall, ActionResult
from finassist.task.action.registry import ActionRegistry


class ActionRunner:

    def __init__(self, action_registry: ActionRegistry):
        self.action_registry = action_registry

    async def run(self, action_call: ActionCall, state: DialogueState) -> ActionResult:
        # 1 按名字找具体 action（找不到会在 registry 里抛带注册清单的 ValueError）
        action: Action = self.action_registry.get_action(action_call.action_name)

        # 2 调具体 action 的 run：里面用 httpx 打中台，返回要更新的槽位
        action_result: ActionResult = await action.run(state=state)
        return action_result
