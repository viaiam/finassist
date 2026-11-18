"""
    @Aythor:Bee
    @Time:2026/11/16
    @Desc:知识检索的"组织话术"层。
          拿到一堆 chunk（可能是商品 JSON、订单 JSON、FAQ 原文），
          丢给 LLM 让它改写成客服口吻，而不是把 JSON 原样甩给用户。
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.knowledge.provider import KnowledgeChunk
from finassist.prompts.history_builder import HistoryBuilder
from finassist.prompts.loader import load_prompt
from finassist.utils.llm import llm


class KnowledgeResponder:

    async def respond(self,
                      chunks: list[KnowledgeChunk],
                      state: DialogueState,
                      user_message: UserMessage) -> BotMessage:
        # 1 提示词 + 调用链
        prompt = PromptTemplate.from_template(
            load_prompt("knowledge_respond"),
            template_format="jinja2",
        )
        chain = prompt | llm | StrOutputParser()

        # 2 多个来源的片段按行拼接：模型能看出这是"几段资料"而不是一整段
        knowledge_content = "\n".join(chunk.content for chunk in chunks if chunk.content)

        # 3 带当前 session 的历史（本轮还没入库，和 ChitChat / Clarify 一致）
        history = HistoryBuilder.build(
            state.shared.sessions[-1].turns if state.shared.sessions else []
        )
        result = await chain.ainvoke({
            "knowledge_content": knowledge_content,
            "history": history,
            "user_message": HistoryBuilder.render_user_message(user_message),
        })
        return BotMessage(text=result)
