"""
意图识别：把一句人话变成结构化的 TurnPlan。整个系统唯一「不可控」的一环。

    @Aythor:Bee
    @Time:2026/11/10
    @Desc:根据用户文本消息，调用大语言模型进行意图识别

■ 它在哪
    engine/dialogue_engine.py 的 _execute_text_message 第一步 → **TurnPlanner.plan()**
      →（产出 TurnPlan）→ plan/turn_plan_validator.py 校验 → 分派

■ 输入 / 输出
    输入：当前 state（历史 + 任务状态 + focused_object）
          本轮 user_message
          流程清单 flow_catalog（告诉模型「你能办哪几种业务」）
    输出：TurnPlan —— 有三种可能，且最多只有一种非空：
          task{commands}      要办业务
          knowledge{intents}  要查信息
          chitchat{}          只是闲聊

■ 一条 LangChain 链，六个输入
    chain = prompt | llm | JsonOutputParser()
    左边是模板，中间是模型，右边是「把模型输出的 JSON 文本解析成 dict」。
    真正喂进模板的是这六个变量：

    | 变量                    | 内容                            | 为什么给模型             |
    |-------------------------|---------------------------------|--------------------------|
    | user_message            | 本轮这句话（带 USER: 前缀）     | 要判断的对象             |
    | conversation_history    | 最近一个 session 的若干轮       | 「刚才说的那单」要靠它   |
    | task_state_json         | 当前 active / paused 任务       | 判断是继续还是换任务     |
    | focused_object_json     | 当前选中的商品/订单             | 「这个」「它」指代什么   |
    | flows_json              | 可办的业务流程（不含步骤）      | 决定要不要 start_flow    |
    | knowledge_intents_json  | 可查的知识类型（只有 id+描述）  | 决定要不要查知识         |

■ ※ 三个「故意不告诉模型」的东西（本模块最值得学的设计）
    1) 流程的 steps 不给：只给 flow_id / 名称 / 描述 / 需要哪些槽位。
       给了步骤，模型会自作主张描述「接下来应该问你订单号」，
       而真正的推进由 FlowExecutor 按 state 走 —— 两套逻辑必然打架。
    2) provider 不给：知识意图只给 id 和描述，去哪取数（中台/FAQ/RAG）
       由 knowledge/intents.py 的映射决定，属于代码的事，不是模型的事。
    3) 具体步骤号不给：task_state_json 里有 step_id，但提示词要求模型
       不要自己算下一步 —— 它只需要决定「开始 / 继续 / 取消 / 换」。

■ ※ 为什么用 JsonOutputParser 而不是让它输出自然语言再正则解析
    这个 parser 会把模型输出当 JSON 解析，并自动在提示词尾部追加
    「只输出 JSON」的指令。解析失败会抛异常 ——
    所以上游必须兜住（目前没兜，属于已知粗糙点：模型偶尔在外面套一层
    JSON 代码块围栏，解析就会炸）。

■ 注意
    plan() 只是「猜」，猜得对不对由 turn_plan_validator 用确定性规则复查，
    所以这里不需要写任何防御性判断 —— 职责单一。
"""
import json
from datetime import datetime, timezone, timedelta
from dataclasses import asdict

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from finassist.domain.state import DialogueState, Turn
from finassist.domain.message import UserMessage
from finassist.knowledge.intents import KNOWLEDGE_INTENTS
from finassist.prompts.history_builder import HistoryBuilder
from finassist.prompts.loader import load_prompt
from finassist.prompts.models import TurnPlan
from finassist.task.flow.models import FlowCatalog, Flow
from finassist.utils.llm import llm


class TurnPlanner:
    async def plan(self, state: DialogueState,
                   user_message: UserMessage,
                   flow_catalog: FlowCatalog) -> TurnPlan:

        # 创建提示词模板
        prompt_text = load_prompt("turn_plan")
        prompt = PromptTemplate.from_template(
            prompt_text,
            template_format="jinja2"
        )
        # 创建调用链
        chain = prompt | llm | JsonOutputParser()

        # 获取 user_message
        user_message_text = HistoryBuilder.render_user_message(user_message)

        # 获取 conversation_history 历史
        ## 取最近一个 session 的所有轮次
        turns: list[Turn] = state.shared.sessions[-1].turns if state.shared.sessions else []
        conversation_history = HistoryBuilder.build(turns)

        # 获取 focused_object_json
        focused_object_json = json.dumps(
            asdict(state.shared.focused_object) if state.shared.focused_object else None,
            ensure_ascii=False
        )

        # 获取 flows_json
        ## 只把流程"是什么"告诉模型，不告诉它"怎么走"
        ## 步骤数据（steps）不进提示词：模型只做意图识别，不推进步骤，
        ## 给了步骤反而容易让它自己编造执行顺序
        flows: dict[str, Flow] = flow_catalog.flows
        flows_json = [
            {
                "flow_id": flow.id,
                "flow_name": flow.name,
                "flow_description": flow.description,
                "flow_slots": [
                    {"name": slot.name, "label": slot.label, "description": slot.description}
                    for slot in flow.slots
                ],
            }
            for flow in flows.values()
        ]

        # 获取 task_state_json
        task_state_json = json.dumps(
            asdict(state.tasks) if state.tasks else None,
            ensure_ascii=False
        )

        # 获取知识检索范围清单
        ## 只给 id + 描述，不给 provider：模型只负责"这是哪类问题"，
        ## 至于去哪取数（中台 / FAQ / RAG）由 intents.py 决定，模型不用知道
        knowledge_intents_json = json.dumps(
            [
                {"id": intent.id, "description": intent.description}
                for intent in KNOWLEDGE_INTENTS.values()
            ],
            ensure_ascii=False,
        )

        # 调用方法，传入数据
        result = await chain.ainvoke(input={
            "current_date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
            "user_message": user_message_text,
            "conversation_history": conversation_history,
            "focused_object_json": focused_object_json,
            "flows_json": json.dumps(flows_json, ensure_ascii=False),
            "knowledge_intents_json": knowledge_intents_json,
            "task_state_json": task_state_json,
        })

        # 把返回的 json 结构转换对象
        return TurnPlan.from_dict(result)
