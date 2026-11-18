"""
全局装配中心：整个后端只在这里 new 一次对象。

    @Aythor:Bee
    @Time:2026/11/13
    @Desc:维护 engine 层的依赖注入关系。
          谁依赖谁，一眼看完；engine 只拿"成品"，不自己在内部 new 一堆东西。

■ 它在哪
    api/app.py 的 lifespan 启动时调 init_dialogue_engine()（见 api/dependencies.py）
      → **build_engine()** → 返回一个装好的 DialogueEngine
    之后每个请求都用这同一个 engine，不再新建。

■ ※ 为什么要专门有一个装配文件（而不是各模块自己 import 自己 new）
    1) 依赖关系集中可见：想知道「谁用了谁」，只读这一个文件就够；
    2) 每个组件只被创建一次（YAML 也只解析一次），不会每请求重复付成本；
    3) 测试时可以把某个组件换成假的，只改这一处；
    4) 避免循环 import：A 需要 B、B 又需要 A 时，让第三方来装配是标准解法。

■ 装配顺序 = 依赖顺序（自底向上，被依赖的先造）

    第 0 步  读 YAML → flow_catalog        （最底层数据，后面到处都要用）
    第 1 步  TurnPlanner / TurnPlanValidator（意图识别 + 校验）
    第 2 步  CommandProcessor / TaskLifecycleResponder / ResponseRender
    第 2.1  ActionRegistry → register_custom_action() → ActionRunner
    第 3 步  FlowExecutor(response_render, action_runner)
    第 4 步  TaskHandler(上面三个)
    第 5 步  ChitChatHandler / ClarifyResponse
    第 6 步  KnowledgeProviderRegistry(4 个 provider) → KnowledgeHandler
    第 7 步  最后把以上全部塞进 DialogueEngine

■ ※ 两个自动化的扩展点（改需求时只需要看一眼这两行）
    register_custom_action(...)：扫 task/action/custom 目录，把里面每个 action 类
      自动注册进注册表 —— 新增一个 action 文件就生效，不用回来改这个文件。
    KnowledgeProviderRegistry(...)：YAML/提示词里只写 provider_id 字符串，
      由注册表映射到具体类 —— 新增数据源也只改注册表。

■ 注意
    这里创建的对象全是「无状态」的（不保存用户数据），所以才能全局共享；
    用户状态一律放在每次请求从数据库读出的 DialogueState 里，绝不挂在组件上。
"""
from pathlib import Path

from finassist.chitchat.chit_chat import ChitChatHandler
from finassist.clarify.clarify_response import ClarifyResponse
from finassist.engine.dialogue_engine import DialogueEngine
from finassist.knowledge.knowledge_handler import KnowledgeHandler
from finassist.knowledge.provider import (
    LoanProductProvider, WealthProductProvider, BankCardProvider, FAQProvider,
)
from finassist.knowledge.registry import KnowledgeProviderRegistry
from finassist.knowledge.responder import KnowledgeResponder
from finassist.plan.turn_plan_validator import TurnPlanValidator
from finassist.plan.turn_planner import TurnPlanner
from finassist.task.action.action_runner import ActionRunner
from finassist.task.action.builder import register_custom_action
from finassist.task.action.registry import ActionRegistry
from finassist.task.command.command_processor import CommandProcessor
from finassist.task.flow.loader import FlowLoader
from finassist.task.flow.models import FlowCatalog
from finassist.task.flowexecutor.flow_executor import FlowExecutor
from finassist.task.response.response_render import ResponseRender
from finassist.task.task_handler import TaskHandler
from finassist.task.tasklifecycle.task_lifecycle import TaskLifecycleResponder

# flow_config 的位置只算一次（别在两个文件里各算一遍）
FLOW_CONFIG_PATH = Path(__file__).parents[2] / 'flow_config' / 'user_flows.yml'


def build_engine() -> DialogueEngine:
    # 0 yaml 只在启动时解析一次（6~7ms/次，每个请求都解析是白付）
    flow_catalog: FlowCatalog = FlowLoader().load(FLOW_CONFIG_PATH)

    # 1 意图识别 + 校验
    turn_planner = TurnPlanner()
    turn_plan_validator = TurnPlanValidator()

    # 2 任务流程：命令 → 话术 → 执行器
    command_processor = CommandProcessor()
    task_lifecycle = TaskLifecycleResponder(flow_catalog=flow_catalog)
    response_render = ResponseRender()

    # 2.1 action 注册表：字符串 name → 具体 action 对象
    # custom 目录下新增一个 action 文件就自动生效，不用回来改这里
    action_registry = ActionRegistry()
    register_custom_action(action_registry=action_registry)
    action_runner = ActionRunner(action_registry=action_registry)

    flow_executor = FlowExecutor(
        response_render=response_render,
        action_runner=action_runner,
    )

    # 3 任务流程对外入口
    task_handler = TaskHandler(
        command_processor=command_processor,
        task_lifecycle=task_lifecycle,
        flow_executor=flow_executor,
        flow_catalog=flow_catalog,
    )

    # 4 另外两条方向：闲聊、澄清
    chit_chat = ChitChatHandler()
    clarify_response = ClarifyResponse()

    # 5 知识检索：4 个 provider 进注册表，handler 只认 provider_id 不认类
    knowledge_registry = KnowledgeProviderRegistry(
        provider_objects=[
            LoanProductProvider(),
            WealthProductProvider(),
            BankCardProvider(),
            FAQProvider(),
        ]
    )
    knowledge_handler = KnowledgeHandler(
        knowledge_registry=knowledge_registry,
        knowledge_responder=KnowledgeResponder(),
    )

    # 6 组装 engine
    return DialogueEngine(
        turn_planner=turn_planner,
        turn_plan_validator=turn_plan_validator,
        task_handler=task_handler,
        chit_chat=chit_chat,
        clarify_response=clarify_response,
        knowledge_handler=knowledge_handler,
        flow_catalog=flow_catalog,
    )
