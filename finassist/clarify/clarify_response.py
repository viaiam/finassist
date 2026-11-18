"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:澄清回复组件。校验不通过时用它兜底说人话：
          先用一张表把 ClarifyReason 翻成"要问什么"，再交给 LLM 结合历史润色。
          语义上属于"兜底话术"，所以不走 task/response（那边是 yaml 里固定话术）。
"""
import json
from dataclasses import asdict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.prompts.history_builder import HistoryBuilder
from finassist.prompts.loader import load_prompt
from finassist.prompts.models import ClarifyReason
from finassist.utils.llm import llm


class ClarifyResponse:

    async def response(self,
                       reason: ClarifyReason,
                       state: DialogueState,
                       user_message: UserMessage) -> list[BotMessage]:
        # 1 提示词：jinja2 格式（课件模板里有 {% if %} 之类的写法）
        prompt = PromptTemplate.from_template(
            load_prompt("clarify_respond"),
            template_format="jinja2",
        )
        chain = prompt | llm | StrOutputParser()

        # 2 先把失败原因翻成一句"要问什么"，再让 LLM 说得自然
        clarify_message = self.build_reason(reason, state)

        result = await chain.ainvoke({
            "reason": reason.value,
            "clarify_message": clarify_message,
            "focused_object": json.dumps(
                asdict(state.shared.focused_object)
                if state.shared.focused_object else None,
                ensure_ascii=False,
            ),
            # 注意：本轮 turn 还没塞进 state（engine 是处理完才 append），
            # 所以历史里天然没有"当前这句"，不会重复
            "history": HistoryBuilder.build(
                state.shared.sessions[-1].turns if state.shared.sessions else []
            ),
            "user_message": HistoryBuilder.render_user_message(user_message),
        })
        return [BotMessage(text=result)]

    # 失败原因 → 一句"要问什么"（LLM 只负责润色，问什么都由这里决定）
    def build_reason(self, reason: ClarifyReason, state: DialogueState) -> str:
        if reason is ClarifyReason.MULTIPLE_TRACKS:
            return ("你这次同时提到了多个方向。我们先处理一个，"
                    "你想先办业务还是先咨询信息呢？")

        if reason is ClarifyReason.MISSING_FOCUSED_OBJECT:
            return "请先发送你想咨询的对象，我再继续帮你看。"

        if reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT:
            return "你是想查询账户、银行卡或贷款，还是咨询金融产品呢？"

        if reason is ClarifyReason.MISSING_TRACK:
            return "你是想先处理业务问题，还是先咨询信息呢？"

        if reason is ClarifyReason.MISSING_TASK_COMMANDS:
            return ("你想查询账户余额、交易流水、贷款状态，还是还款计划呢？")

        if reason is ClarifyReason.INVALID_TASK_COMMAND:
            return ("当前任务状态不支持这个操作，"
                    "请告诉我你想开始、继续还是取消哪个任务。")

        if reason is ClarifyReason.UNKNOWN_KNOWLEDGE_INTENT:
            return ("我暂时无法识别这个咨询方向，"
                    "你可以具体说说想查询的账户、贷款或金融产品。")

        if reason is ClarifyReason.OBJECT_REQUIRES_INTENT:
            focused_object = state.shared.focused_object
            if focused_object is not None and focused_object.type == 'account':
                return '已选中这个账户。你想查余额还是交易流水？'
            if focused_object is not None and focused_object.type == 'loan':
                return '已选中这笔贷款。你想查贷款状态还是还款计划？'
            if focused_object is not None and focused_object.type in ('loan_product', 'wealth_product'):
                return '已选中这个金融产品。你想了解利率、风险等级还是产品条件？' 
            if focused_object is not None and focused_object.type == "order":
                return "我已经收到这个订单了。你想查订单状态、查物流，还是申请退款呢？"
            if focused_object is not None and focused_object.type == "product":
                return ("我已经收到这个商品了。你想了解它的商品信息、"
                        "发货情况，还是售后相关问题呢？")

        # 兜底：万一是新加的 reason 没写在这里
        return "我还需要再确认一下你的意思，你可以换个更具体的说法告诉我。"
