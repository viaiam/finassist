"""
    @Aythor:Bee
    @Time:2026/11/16
    @Desc:知识检索入口。五步：
          1 LLM 给出意图 id 列表            ["product_info", "refund_policy"]
          2 翻成答案位置，顺序去重            ["api.product", "faq.default", "rag.default"]
          3 答案位置 → provider 对象
          4 并发/顺序执行 provider，拿回 chunk
          5 chunk 交给 responder 改写成人话
"""
from finassist.domain.message import BotMessage, UserMessage
from finassist.domain.state import DialogueState
from finassist.knowledge.intents import KNOWLEDGE_INTENTS
from finassist.knowledge.provider import KnowledgeChunk, KnowledgeError
from finassist.knowledge.registry import KnowledgeProviderRegistry
from finassist.knowledge.responder import KnowledgeResponder


class KnowledgeHandler:

    def __init__(self,
                 knowledge_registry: KnowledgeProviderRegistry,
                 knowledge_responder: KnowledgeResponder):
        self.knowledge_registry = knowledge_registry
        self.knowledge_responder = knowledge_responder

    async def handle(self,
                     knowledge_intents: list[str],
                     state: DialogueState,
                     user_message: UserMessage) -> list[BotMessage]:
        # 1-2 意图 id → 答案位置
        provider_ids = self.get_provider_ids(knowledge_intents)
        if not provider_ids:
            # 模型编了字典里没有的意图（校验层只检查"有没有"，不检查"对不对"）
            return [BotMessage(text="抱歉，我没太理解你想咨询哪方面的内容，能再说具体一点吗？")]

        # 3-4 依次执行 provider，结果合并
        chunks: list[KnowledgeChunk] = []
        try:
            for provider_id in provider_ids:
                provider = self.knowledge_registry.get_provider(provider_id)
                chunks.extend(await provider.execute(
                    state=state,
                    user_message=user_message,
                ))
        except KnowledgeError as exc:
            # 前置条件不满足（比如没选商品）——直接回一句人话，
            # 别把 "未检索到" 这种空资料喂给 LLM 让它自由发挥
            return [BotMessage(text=str(exc))]

        # 5 交给 LLM 组织语言
        bot_message = await self.knowledge_responder.respond(
            chunks=chunks,
            state=state,
            user_message=user_message,
        )
        return [bot_message]

    def get_provider_ids(self, knowledge_intents: list[str]) -> list[str]:
        provider_ids: list[str] = []
        for intent in knowledge_intents:
            intent_def = KNOWLEDGE_INTENTS.get(intent)
            if intent_def is None:
                # 课程代码是 KNOWLEDGE_INTENTS[intent] → KeyError → 500
                continue
            provider_ids.extend(intent_def.provider_ids)

        # 顺序去重：set 的迭代顺序不稳定，同一句话两次请求可能走不同 provider 顺序，
        # 拼出来的 knowledge_content 顺序一乱，LLM 的答案也会飘。
        # dict.fromkeys 既去重又保序。
        return list(dict.fromkeys(provider_ids))
