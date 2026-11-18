"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:action 注册表。yaml 里写的是字符串（action_lookup_order_status），
          字符串 → 对象 的映射放这里，FlowExecutor 只认 ActionRunner，不认具体类。
"""
from finassist.task.action.base import Action


class ActionRegistry:
    def __init__(self):
        # {action 名字: action 对象}
        self.actions: dict[str, Action] = {}

    # 注册：重复注册同名 action 直接覆盖（后续接包扫描时方便热替换）
    def register(self, action: Action):
        self.actions[action.name] = action

    # 取：找不到时给一个能指到 yaml 的报错，而不是一个裸 KeyError
    def get_action(self, name: str) -> Action:
        action = self.actions.get(name)
        if action is None:
            raise ValueError(
                f"未注册的 action：{name}（已注册：{', '.join(sorted(self.actions))}）"
            )
        return action
