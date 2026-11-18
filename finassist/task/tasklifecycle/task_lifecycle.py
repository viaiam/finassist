"""
任务生命周期话术：把「事件」翻译成一句中文提示。

    @Aythor:Bee
    @Time:2026/11/13
    @Desc:根据 commandProcessor 组件返回的任务状态变化对象列表（list[TaskEvent]）生成不同的中文提示
    只负责说人话，不碰 state，也不碰流程推进

■ 它在哪
    task/command/command_processor.py（改数据、出事件）
      → **本文件 respond()**（事件 → 一句话）
      → task/task_handler.py 把这几句和流程正文拼起来

■ 四个事件对应四句话（一一对应，没有分支嵌套）

    | 事件         | 触发场景                     | 说的话                              |
    |--------------|------------------------------|-------------------------------------|
    | TaskStarted  | 原本没任务，现在开一个       | 好的，现在开始执行{流程名}          |
    | TaskSwitched | 本来有任务，用户换了另一个   | 好的，现在把{旧}暂停，现在开始执行{新} |
    | TaskResumed  | 用户回到之前挂起的任务       | 好的，继续刚才{流程名}操作          |
    | TaskCanceled | 用户取消任务                 | 好的，取消{流程名}操作              |

■ ※ 为什么它需要 flow_catalog
    事件里只有 flow_id（order_status_query 这种英文 id），
    念给用户听要用 yaml 里的 name（「订单状态查询」）。
    所以这里要查一次表，把 id 换成中文名。
    ※ 这也是「事件只携带引用、不携带文案」的直接后果：
      话术层负责查名字，数据层不需要关心怎么说。

■ ※ 为什么这些句子是硬编码而不是让 LLM 写
    这四句是「系统提示音」，必须稳定、即时、零成本。
    真正需要自然语言表达的是流程正文（ResponseRender 那边），
    两者分工不同 —— 别为了用模型而用模型。

■ 一个小瑕疵（可以自己动手改）
    最后的 return BotMessage(text="兜底数据") 是兜底分支，
    「兜底数据」这四个字万一真的发给用户会很难看。
    更稳妥的写法是 return None 或者干脆不 append（见 respond 里的循环）。
"""
from finassist.domain.message import BotMessage
from finassist.lifecycle.models import (
    TaskEvent, TaskStarted, TaskSwitched, TaskResumed, TaskCanceled,
)
from finassist.task.flow.models import FlowCatalog, Flow


class TaskLifecycleResponder:

    def __init__(self, flow_catalog: FlowCatalog):
        self.flow_catalog = flow_catalog

    async def respond(self, events: list[TaskEvent]) -> list[BotMessage]:
        messages: list[BotMessage] = []
        # 遍历 list[TaskEvent]，一个事件一句话
        for event in events:
            messages.append(self.execute_event_data(event))
        return messages

    # 根据流程 id 获取流程名称（yaml 里每条 flow 都有 name，比 id 适合念给用户听）
    def _get_flow_name(self, flow_id: str) -> str:
        flow: Flow = self.flow_catalog.get_flow_by_id(flow_id)
        return flow.name or flow_id

    # 根据 event 不同类型生成不同中文提示
    def execute_event_data(self, event: TaskEvent) -> BotMessage:
        if isinstance(event, TaskStarted):
            flow_name = self._get_flow_name(event.task.flow_id)
            return BotMessage(text=f"好的，现在开始执行{flow_name}")

        if isinstance(event, TaskSwitched):
            pre_flow_name = self._get_flow_name(event.previous.flow_id)
            current_flow_name = self._get_flow_name(event.current.flow_id)
            return BotMessage(text=f"好的，现在把{pre_flow_name}暂停，现在开始执行{current_flow_name}")

        if isinstance(event, TaskResumed):
            flow_name = self._get_flow_name(event.task.flow_id)
            return BotMessage(text=f"好的，继续刚才{flow_name}操作")

        if isinstance(event, TaskCanceled):
            flow_name = self._get_flow_name(event.task.flow_id)
            return BotMessage(text=f"好的，取消{flow_name}操作")

        return BotMessage(text="兜底数据")
