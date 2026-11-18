"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:闲聊处理器。意图识别判定"既不办业务、也不查知识"时走到这里，
          直接让 LLM 带着最近历史回一句话。
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.prompts.history_builder import HistoryBuilder
from finassist.prompts.loader import load_prompt
from finassist.utils.llm import llm


class ChitChatHandler:

    async def chit_chat(self,
                        state: DialogueState,
                        user_message: UserMessage) -> list[BotMessage]:
        # 1 提示词 + 调用链
        prompt = PromptTemplate.from_template(
            load_prompt("chitchat_respond"),
            template_format="jinja2",
        )
        chain = prompt | llm | StrOutputParser()

        # 2 带上当前 session 的历史（本轮还没入 history，见 ClarifyResponse 里的说明）
        history = HistoryBuilder.build(
            state.shared.sessions[-1].turns if state.shared.sessions else []
        )
        result = await chain.ainvoke({
            "history": history,
            "user_message": HistoryBuilder.render_user_message(user_message),
        })
        return [BotMessage(text=result)]
