"""
task/response/models.py —— 话术模板的数据模型 + 三种渲染模式

■ 它是什么
    YAML 里 response 步骤要配置「说什么话」，有两种写法：
        template: "您的订单 {{ slots.order_number }} 已发货"      → 纯字符串
        template:
          content: "您的订单 {{ slots.order_number }} 已发货"
          mode: rephrase                                       → 带模式的字典
    本文件把这两种写法统一成 ResponseTemplate。

■ ResponseMode 三种模式的区别（选型要点，很实用）
    static    模板渲染完直接发。快、可预测，但话术是死的，稍显机械。
    rephrase  先渲染，再让 LLM 换个更自然的说法，且要求不改变事实。
              自然度↑，但会增加一次 LLM 调用（延迟、成本、可能改错事实）。
    generate  不给模板，直接让 LLM 根据上下文自由生成。最灵活，最不可控。

    ※ 从 static 到 generate，可控性递减、自然度递增。
      客服场景里涉及金额、订单号这类硬事实时，优先 static / rephrase。

■ 在调用链中的位置
    yaml 的 response 步骤
        ↓  task/flow/steps.py::ResponseFlowStep（持有 ResponseTemplate）
        ↓  task/response/response_render.py::ResponseRender.render()
    渲染出的 BotMessage

■ 容错的取舍
    ResponseTemplate.from_dict 遇到任何不认识的形状都会「退化」成 static 模式，
    ※ 这是有意为之：宁可话术朴素一点，也不能因为配置写错就让整轮对话抛异常。
"""
from dataclasses import dataclass
from enum import Enum


class ResponseMode(Enum):
    # 直接返回text内容
    STATIC = "static"

    # 基于text内容，调用llm，把text修改返回
    REPHRASE = "rephrase"

    # 直接llm生成内容 返回
    GENERATE = "generate"


@dataclass
class ResponseTemplate:
    mode: ResponseMode = ResponseMode.STATIC
    text: str | None = None
    prompt: str | None = None

    @classmethod
    def from_dict(cls,template_data:dict
                    )->"ResponseTemplate":
        # mode 从 yaml 里读，读不到（或者写错）就退化成 static
        mode_data = template_data.get('mode')
        try:
            mode = ResponseMode(mode_data) if mode_data else ResponseMode.STATIC
        except ValueError:
            mode = ResponseMode.STATIC
        return cls(
            mode=mode,
            text=template_data.get('text'),
            prompt=template_data.get('prompt') )


