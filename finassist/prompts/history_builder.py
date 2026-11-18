"""
prompts/history_builder.py —— 把历史对话拼成一段纯文本，塞进提示词

■ 它是什么
    LLM 不认识 DialogueState 这种对象，只认识文本。
    这个模块负责把「最近 N 轮」压成一段带前缀的纯文本：

        USER: 我想查订单 A1001
        BOT: 好的，现在开始执行订单状态查询
        BOT: 请告诉我您的订单编号
        USER: A1001
        BOT: 您的订单已发货，预计明天送达

■ 在调用链中的位置
    plan/turn_planner.py / clarify_response.py / chit_chat.py / knowledge/responder.py
        都调 HistoryBuilder.build(session.turns, limit)   ← 你在这里
        ↓ 返回的字符串被填进各自 jinja2 模板的 {{ conversation_history }} 位置

■ 为什么只取最近几轮（limit 参数）
    ※ 上下文越长越贵，而且模型更容易被很早以前的话题带跑。
      客服场景里，用户三句话前说的话通常才有用。
      注意：任务真正的记忆不靠这段文本，而靠 slots 里的结构化数据 ——
      历史文本只是让模型听懂「你刚说的那个」的指代。

■ 关键细节
    · 用户消息如果是对象类型（没文本），会被渲染成一行占位说明，
      否则模型会看到一行空的 USER:，误以为用户没说话；
    · 字段用 asdict 展开，URL 之类的额外键会作为附注跟在后面。
"""
import json
from dataclasses import asdict

from finassist.domain.message import UserMessage, MessageType, BotMessage
from finassist.domain.state import Turn


class HistoryBuilder:

    @staticmethod
    def build(turns: list[Turn]) -> str:
        messages: list[str] = []
        for turn in turns:
            user_message = HistoryBuilder.render_user_message(turn.user_message)
            messages.append(user_message)
            for bot_message in turn.bot_message:
                bot_message = HistoryBuilder.render_bot_message(bot_message)
                messages.append(bot_message)
        return "\n".join(messages)

    @staticmethod
    def render_user_message(user_message: UserMessage) -> str:
        if user_message.type == MessageType.TEXT:
            return f"USER: {user_message.text}"
        else:
            return f"USER: {json.dumps(asdict(user_message.object), ensure_ascii=False)}"

    @staticmethod
    def render_bot_message(bot_message: BotMessage) -> str:
        if bot_message.text:
            return f"BOT: {bot_message.text}"
        else:
            return f"BOT: {json.dumps(asdict(bot_message.object), ensure_ascii=False)}"
