"""
service 层：一次对话请求的「编排者」。

■ 它在哪
    api/chat_router.py  →  **本文件的 DialogueService.run()**  →  engine/dialogue_engine.py

■ 它只干三件事（顺序不能乱）
    1) 按 sender_id 从数据库读回这个人的完整状态 DialogueState（repository.load_state）
    2) 把「状态 + 这条新消息」交给引擎跑一轮，拿到要回复的内容（engine.process_message）
    3) 把引擎**改过的同一个 state 对象**写回数据库（repository.save_state）

■ ※ 为什么这一层薄得只有 15 行？
    它就是「事务脚本」：读 → 算 → 写。业务知识全在 engine 和 task 里，
    这一层只负责把「数据库」和「对话引擎」这两件互不认识的东西粘起来。
    好处是：想换成内存存储、想加缓存、想加审计日志，都只改这里，引擎不用动。

■ ※ 第 3 步能直接存，是因为 process_message 是「就地修改」
    engine 拿到的 state 是引用，它内部的 start_task / 写 slots / 追加 turn
    全都在改调用方传进去的这同一个对象。所以这里不需要 engine 返回新状态。

■ 一个容易忽略的细节
    即使引擎抛异常，load_state 已经发生、save_state 不会执行 —— 状态不会写脏。
    这就是把 commit 放在 save_state 里（而不是 run 里）带来的好处。
"""
from finassist.domain.message import UserMessage, ProcessResult
from finassist.domain.state import DialogueState
from finassist.engine.dialogue_engine import DialogueEngine
from finassist.repository.dialogue_repository import DialogueRepository


class DialogueService:

    def __init__(self, repository: DialogueRepository,
                      engine: DialogueEngine):
        self.repository = repository
        self.engine = engine

    async def run(self, user_message:UserMessage)->ProcessResult:
        # 1 注入要调用层对象，repository对象（操作数据库） 和 engine对象（处理消息）
        # 2 根据sender_id获取当前用户历史消息处理数据
        sender_id = user_message.sender_id
        # 调用repository层方法进行查询
        state:DialogueState = await self.repository.load_state(sender_id)

        # 3 调用engine层方法处理当前消息
        process_result:ProcessResult = (
            await self.engine.process_message(state, user_message))

        # 4 把处理消息之后最新处理数据保存数据库里面
        await self.repository.save_state(state)

        # 5 返回engine处理结果
        return process_result