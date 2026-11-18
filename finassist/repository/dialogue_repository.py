"""
repository/dialogue_repository.py —— 对话状态的读写（MySQL 单表）

■ 它是什么
    只有两个方法：
        load_state(sender_id)  → 查一行，反序列化成 DialogueState；查不到就返回一个全新的空状态
        save_state(state)      → 把整个状态序列化成 JSON，upsert 回那一行

■ 在调用链中的位置
    service/dialogue_service.py::run()
        state = await repository.load_state(sender_id)      ← 进入
        ... engine 在内存里改这个对象 ...
        await repository.save_state(state)                  ← 出去
    ※ repository 是唯一碰数据库的地方，engine/task/knowledge 全都不认识 MySQL。

■ 三个值得记住的设计点

  1) 为什么整棵树存成一列 TEXT，而不是拆成 turns/tasks/slots 多张表？
     ※ 状态是「一次读、一次写、整体用」的：没有任何查询需要按 slots 里的值做筛选。
       拆表会带来 join、外键、部分更新的一致性麻烦，收益为零。
       代价是：无法用 SQL 做局部更新，也没法按内容检索 —— 这个场景下可以接受。

  2) 为什么用 pydantic 的 TypeAdapter 而不是 pickle / json.dumps？
     ※ DialogueState 里嵌套着 dataclass、Enum、float、dict，
       TypeAdapter(DialogueState) 知道怎么把整个类型树双向转换；
       而 json.dumps 处理不了 dataclass 和 Enum，pickle 则有版本与安全风险。

  3) 为什么用 MySQL 的 INSERT ... ON DUPLICATE KEY UPDATE 而不是「先查后写」？
     ※ 先 SELECT 再 INSERT/UPDATE 有并发窗口：同一用户连发两条消息，
       两个请求可能都判定「不存在」然后双双 INSERT，主键冲突报错。
       交给数据库一条原子语句解决，幂等且无竞态。

■ 注意
    · upsert 用的是 dialects.mysql 的 insert，换数据库（如 PostgreSQL）要换成
      postgresql.insert().on_conflict_do_update(...)；
    · save_state 末尾显式 await self.session.commit() —— 一个请求一个事务，
      提交后连接由 get_session 的 async with 归还（见 api/dependencies.py）。
"""
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from finassist.domain.state import DialogueState
from finassist.repository.orm.dialogue_state import DialogueStateRecord

# 类型适配器：DialogueState 对象与 JSON 字符串互转
#   json 字符串 --对象：validate_json()
#   对象 --json 字符串：dump_json()
# ※ 它在**模块级**创建（整个进程一个），不是每次请求 new 一个：
#   构建 TypeAdapter 要遍历整个类型树生成 schema，属于重活，做一次就够。
# json字符串 -- 对象：validate_json()
# 对象 -- json字符串：dump_json()
dialogue_state_adapter = TypeAdapter(DialogueState)

class DialogueRepository:

    # 注入操作数据库session对象
    def __init__(self,session:AsyncSession):
        self.session = session

    # 根据sender_id查询
    async def load_state(self,
                     sender_id:str)->DialogueState:
        # 第一种 编写sql语句
        # sql = "select * from dialogue_states where sender_id = :sid"
        # result = await self.session.execute(sql,{"sid":sender_id})

        # 第二种 orm思想
        # 不需要编写sql语句，对象形式操作
        ## 第一步 构建语句
        sql = select(DialogueStateRecord).where(
                     DialogueStateRecord.sender_id == sender_id)

        ## 第二步 调用session方法执行语句
        result = await self.session.execute(sql)

        ## 第三步 得到最终结果
        record = result.scalar_one_or_none()

        ## 结果处理
        if record: # 查询到结果，把查询json字符串 转换 DialogueState对象
            state = dialogue_state_adapter.validate_json(record.state_json)
            return state
        else: # 没有查询到结果 none
            return DialogueState(sender_id=sender_id)

    # 保存数据库
    ## 不存在添加，存在更新
    async def save_state(self, state:DialogueState):
        # 第一步 state对象 转换 json字符串  dump_json()
        state_json = dialogue_state_adapter.dump_json(state).decode("utf-8")

        # 第二步 构建sql语句
        ## 判断表里面存在数据更新，不存在添加
        # insert into dialogue_states values(1,'{....}')
        # update dialogue_states set state_json=? where sender_id=1

        # 如果只是想实现基本添加操作，导入通用 或者方言mysql依赖都可以的
        ## 标准sql   方言sql
        # 因为现在逻辑：存在数据更新，不存在添加
        ## 如果原始方式：先查询数据，有更新，没有添加
        ## 但是使用sqlalchemy封装这个实现，只需要导入方言insert依赖，直接调用方法实现这个逻辑
        ### from sqlalchemy.dialects.mysql import insert
        sql = insert(DialogueStateRecord).values(
            sender_id=state.sender_id,
            state_json=state_json
        )
        # 存在数据更新，不存在添加
        on_duplicate_key = sql.on_duplicate_key_update(
            state_json=state_json
        )

        # 第三步 执行语句
        await self.session.execute(on_duplicate_key)
        await self.session.commit()