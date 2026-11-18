"""
lifecycle/models.py —— 任务事件（「状态变了」的四种说法）

■ 它是什么
    只定义 4 个 dataclass，描述「任务状态发生了哪种变化」：
        TaskStarted   0 → 1      从没任务变成有任务
        TaskSwitched  有任务时又开了新任务（旧的被压进 paused）
        TaskResumed   从暂停队列里恢复某个任务
        TaskCanceled  取消掉某个任务

■ 为什么要把「事件」单独定义出来（本项目最重要的一处解耦，务必抓住）

        task/command/command_processor.py     只管改 state，**产出事件**，不说话
                        ↓  list[TaskEvent]
        task/tasklifecycle/task_lifecycle.py  只管把事件翻成中文话术，**不碰 state**

    ※ 好处有三：
      1) 状态修改和话术生成能分开测 —— 前者断言 state 的字段，后者只看事件对象；
      2) 想改口播（「好的，现在开始执行XX」），只碰 task_lifecycle.py，
         绝不会误伤任务状态机；
      3) 一轮里可能连发多个命令（start_flow + set_slots），事件列表天然支持
         「一命令一条提示」的批量播报；而 set_slots 故意不产生事件（返回 None），
         用户就不会看到多余的一句话。

■ TaskRef 和 TaskInstance 的区别（初学者最容易混）
    TaskInstance（在 domain/state.py）是**完整**任务：带 slots 槽位、带 step_id 进度；
    TaskRef（本文件）是**轻量引用**：只有 task_id + flow_id。
    ※ 事件里只放 TaskRef，一是防止话术层顺手改到槽位，
      二是别把一大坨 slots 塞进事件流和日志里。
"""
from dataclasses import dataclass
from typing import TypeAlias


@dataclass
class TaskRef:
    task_id: str
    flow_id: str

# 开始任务变化
@dataclass
class TaskStarted:
    task: TaskRef

# 切换任务变化
@dataclass
class TaskSwitched:
    previous: TaskRef
    current: TaskRef

# 恢复任务变化
@dataclass
class TaskResumed:
    task: TaskRef

# 取消任务变化
@dataclass
class TaskCanceled:
    task: TaskRef


TaskEvent: TypeAlias = (
        TaskStarted
        | TaskSwitched
        | TaskResumed
        | TaskCanceled
)