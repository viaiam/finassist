"""
task/flow/steps.py —— 流程步骤的五种类型（YAML 里 steps 一节的「类定义」）

■ 它是什么
    YAML 里一条流程由若干步骤串起来，每步靠 type 字段声明自己是哪一类。
    本文件把 type 字符串翻译成五个 Python 类：

        type: start      → StartFlowStep     起点，一进流程就先走它
        type: collect    → CollectSlotStep   收集槽位；槽位为空就停下来问用户
        type: action     → ActionFlowStep    调外部动作（查订单、查物流…）
        type: response   → ResponseFlowStep  渲染一句客服话术
        type: end        → EndFlowStep       终点，清空 active，任务结束

■ 在调用链中的位置
    flow_config/user_flows.yml
        ↓  task/flow/loader.py          读 yaml
        ↓  FlowStep.from_dict()         ← 你在这里：按 type 分派到具体类
    五个步骤对象组成的 list → task/flow/models.py::Flow
        ↓
    task/flowexecutor/flow_executor.py::execute()
        用 isinstance 判断是哪种步骤，走对应分支

■ 三种基类字段（所有步骤共有，对应 yaml 里每步都能写的 key）
        id          步骤唯一 id，next 里的 target 就是它
        type        类型字符串
        next        「下一步去哪」，可以是字符串，也可以是带 if 的列表
                    → 由 _build_links() 解析成 task/flow/links.py 里的三种连线
        description 给人看的备注，运行期不参与逻辑

■ 关键概念
    from_dict 是「工厂方法」：调用方只说「这是一坨 dict」，
    具体 new 哪个类由类型表决定，调用方不需要写 if/else。
    ※ 想加一种新步骤类型：写一个类 + 在 TYPE_TO_STEP_CLASS 里登记一行即可，
      FlowExecutor 里再加一个 isinstance 分支。两处，很集中。

■ 关于 Any
    下面用 dict[str, Any] 接 yaml 原始数据 —— yaml 结构天然是松散的，
    这里刻意不做严格校验，容错交给各子类的 __post_init__ / 默认值。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from finassist.task.flow.links import FlowStepLink, StaticLink, ConditionalLink, FallbackLink
from finassist.task.response.models import ResponseTemplate

class FlowStepType(Enum):
    START = "start"
    ACTION = "action"
    RESPONSE = "response"
    COLLECT = "collect"
    END = "end"

@dataclass
class FlowStep:
    id: str
    type: FlowStepType
    next: list[FlowStepLink] = field(default_factory=list)
    description: str = ""

    # 前向引用
    # {id:start , type: start}
    @classmethod
    def from_dict(cls, flow_step_data: dict[str, Any]) -> "FlowStep":
        # start
        flow_type = flow_step_data['type']
        # type= start   得到类 StartFlowStep
        clz = TYPE_TO_STEP_CLASS[flow_type]
        # StartFlowStep.from_dict(flow_step_data)
        return clz.from_dict(flow_step_data)

    @classmethod
    def base_fields(cls, flow_step_data: dict[str, Any]) -> dict[str, Any]:
        return {
            'id': flow_step_data['id'],
            'type': FlowStepType(flow_step_data['type']),
            'description': flow_step_data.get('description', ''),
            'next': cls._build_links(flow_step_data['next'])
        }

    # todo
    @classmethod
    def _build_links(cls, next_data: str | list[dict]) -> list[FlowStepLink]:
        # 判断next_data的类型，如果是字符串，则调用StaticLink.from_dict，如果是列表，则调用ConditionalLink.from_dict
        if isinstance(next_data, str):
            return [StaticLink(target=next_data)]
        elif isinstance(next_data, list):
            link_list: list[FlowStepLink] = []
            #把next_data遍历
            for link_data in next_data:
                if 'if' in link_data:
                    link_list.append(ConditionalLink(condition=link_data['if'], target=link_data['then']))
                else:#else分支
                    link_list.append(FallbackLink(target=link_data['else']))

            return link_list
        else:
            raise ValueError(f"Invalid next_data: {next_data}")

@dataclass
class StartFlowStep(FlowStep):
    # 前向引用
    # {a:1,b:2} == StartFlowStep对象
    @classmethod
    def from_dict(cls, flow_step_data: dict[str, Any]) -> "StartFlowStep":
        return cls(**FlowStep.base_fields(flow_step_data))

@dataclass
class ActionFlowStep(FlowStep):
    action: str = ""

    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, flow_step_data: dict[str, Any]) -> "ActionFlowStep":
        return cls(
            **FlowStep.base_fields(flow_step_data),
            action=flow_step_data['action'],
            args=flow_step_data.get('args', {})
        )

@dataclass
class ResponseFlowStep(FlowStep):
    template: ResponseTemplate = field(default_factory=ResponseTemplate)

    @classmethod
    def from_dict(cls, flow_step_data: dict[str, Any]) -> "ResponseFlowStep":
        # pass
        return cls(
            **FlowStep.base_fields(flow_step_data),
            template=ResponseTemplate.from_dict(
                        flow_step_data['template'])
        )

@dataclass
class CollectSlotStep(FlowStep):
    slot_name: str = ""
    template: ResponseTemplate = field(default_factory=ResponseTemplate)

    @classmethod
    def from_dict(cls, flow_step_data: dict[str, Any]) -> "CollectSlotStep":
        # 加载逻辑
        return cls(
            **FlowStep.base_fields(flow_step_data),
            slot_name=flow_step_data['slot_name'],
            template=ResponseTemplate.from_dict(flow_step_data['template'])
        )

@dataclass
class EndFlowStep(FlowStep):

    @classmethod
    def from_dict(cls, flow_step_data: dict[str, Any]) -> "EndFlowStep":
        return cls(**FlowStep.base_fields(flow_step_data))

TYPE_TO_STEP_CLASS = {
    'start': StartFlowStep,
    'collect': CollectSlotStep,
    'response': ResponseFlowStep,
    'action': ActionFlowStep,
    'end': EndFlowStep
}
