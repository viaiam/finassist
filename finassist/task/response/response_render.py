"""
话术渲染：把 yaml 里的模板变成用户看到的那句话。

    @Aythor:Bee
    @Time:2026/11/13
    @Desc:使用 jinja2 渲染 yaml 里的话术模板，返回 BotMessage
    three modes:
        static   —— 模板原样渲染，最确定、最省钱，默认走这条
        rephrase —— 先渲染出事实，再让 LLM 润色成人话
        generate —— 直接让 LLM 生成（没有事实可锚，慎用）

■ 它在哪
    task/flowexecutor/flow_executor.py 的 response / collect 两类步骤 →
    **ResponseRender.render()** → 产出 BotMessage

■ 三种模式：可控性、成本、灵活性的三角

    | 模式     | 做法                                | 成本 | 会不会说错事实 |
    |----------|-------------------------------------|------|----------------|
    | static   | jinja2 直接填槽位                   | 0    | 不会           |
    | rephrase | 先渲染出事实，再让 LLM 换个说法     | 1 次 | 基本不会（有原文锚着）|
    | generate | 只给提示词，让 LLM 自由写           | 1 次 | 会             |

    ※ 默认 static：能确定的事就别问模型。模型只在「需要变着花样哄人」时才上。
    ※ rephrase 的关键是 current_response 这个变量：把已经算好的事实交给模型，
      它的任务被压缩成「改写」而不是「回答」，幻觉空间小得多。

■ 槽位从哪来
    state.tasks.active.slots —— 模板里写 {{ slots.order_number }} 就取这个。
    ※ 所有 action 步骤的执行结果都写进 slots，所以模板能直接引用，不用单独传参。

■ ※ 为什么用 jinja2 的 Template，而不用 LangChain 的 PromptTemplate
    PromptTemplate 会把模板里所有 { } 都当成变量占位符，
    而客服话术里难免出现花括号（比如 JSON 示例），会被误伤。
    jinja2 的 Template(text).render(slots=slots) 更宽容，
    而且 yaml 里写的 {{ }} 本来就是 jinja2 语法。

■ 兜底
    未知 mode 返回空字符串而不是 None —— 上层会直接拿去组 BotMessage，
    返回 None 会在更远的地方炸，报错信息还看不出根因。
"""
from jinja2 import Template
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.prompts.history_builder import HistoryBuilder
from finassist.task.response.models import ResponseTemplate, ResponseMode
from finassist.utils.llm import llm


class ResponseRender:

    async def render(self,
                     template: ResponseTemplate,
                     state: DialogueState,
                     user_message: UserMessage) -> BotMessage:
        # 槽位数据：模板里所有 {{ slots.xxx }} 都从这里取
        slots = state.tasks.active.slots if state.tasks.active else {}

        # 1 静态渲染：yaml 写什么就回什么
        if template.mode == ResponseMode.STATIC:
            return BotMessage(text=self._render_jinja2(template.text or "", slots))

        # 2 润色：先渲染出确定的事实，再让 LLM 换一种说法
        if template.mode == ResponseMode.REPHRASE:
            render_text = self._render_jinja2(template.text or "", slots)
            prompt = PromptTemplate.from_template(
                template.prompt or "",
                template_format="jinja2",
            )
            chain = prompt | llm | StrOutputParser()
            result = await chain.ainvoke({
                "history": self._build_history(state),
                "user_message": HistoryBuilder.render_user_message(user_message),
                "current_response": render_text,
            })
            return BotMessage(text=result)

        # 3 生成：没有事实锚点，让 LLM 自己写（yaml 里目前没用）
        if template.mode == ResponseMode.GENERATE:
            prompt = PromptTemplate.from_template(
                self._render_jinja2(template.prompt or "", slots),
                template_format="jinja2",
            )
            chain = prompt | llm | StrOutputParser()
            result = await chain.ainvoke({
                "history": self._build_history(state),
                "user_message": HistoryBuilder.render_user_message(user_message),
            })
            return BotMessage(text=result)

        # 兜底：未知 mode 不应该发生，但别把 None 扔给上层
        return BotMessage(text="")

    # jinja2 渲染（注意：这里不能用 PromptTemplate，
    # 因为话术模板里可能有 {{ }} 之外的花括号，PromptTemplate 会当成变量）
    def _render_jinja2(self, text: str, slots: dict) -> str:
        return Template(text).render(slots=slots)

    # 历史对话：取最新 session 的所有轮次
    def _build_history(self, state: DialogueState) -> str:
        if not state.shared.sessions:
            return ""
        return HistoryBuilder.build(state.shared.sessions[-1].turns)
