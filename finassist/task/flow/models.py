"""
task/flow/models.py —— 流程（Flow）与流程目录（FlowCatalog）

■ 它是什么
    YAML 解析成内存对象后的两个核心容器：
        FlowSlot     一个槽位的「元信息」：叫什么、什么类型、给模型看的说明
        Flow         一条完整流程：id + 说明 + 步骤列表 + 槽位列表
        FlowCatalog  一次加载的全部结果：所有流程 + 所有槽位定义（全局索引）

■ 在调用链中的位置
    flow_config/user_flows.yml
        ↓  task/flow/loader.py::FlowLoader.load()
    本文件的 FlowCatalog
        ↓  engine/builder.py 装配时创建一次，挂在 FlowExecutor 上（全局复用）
        ↓
    task/flowexecutor/flow_executor.py   按 task.flow_id 取 Flow
    plan/turn_planner.py                 把整个 catalog 序列化成 JSON 塞进提示词，
                                         让模型知道「系统支持哪些流程、哪些槽位」

  ※ 为什么要在启动时把 yaml 解析一次就缓存住？
    yaml 是静态配置，运行期不会变；每次请求都读盘 + 解析纯属浪费。
    所以 builder.py 里只 load 一次，之后全靠内存里的 FlowCatalog。

■ 关键概念
    FlowSlot  槽位 = 流程要收集的「一个变量」。
              它本身不存值，存值的地方是 TaskInstance.slots（见 domain/state.py）。
              ※ 容易混：FlowSlot 是「声明」（这个流程需要 order_number），
                        TaskInstance.slots 是「实例」（这一单的 order_number 是 A1001）。
"""
from dataclasses import dataclass, field
from finassist.task.flow.steps import FlowStep, StartFlowStep


# ==========================================================================
# 槽位声明
# ==========================================================================
@dataclass
class FlowSlot:
    """一个槽位的元信息（来自 yaml 顶部的 slots: 段落）。

    示例（yaml）：
        slots:
          order_number:
            type: string
            label: 订单号
            description: 用户要查询的订单编号

    ※ label / description 不只是给人看的 —— turn_plan.jinja2 会把整个 catalog
      序列化成 JSON 交给大模型，模型靠 description 判断「该不该启动这条流程」。
      所以这两个字段写得越清楚，意图识别越准。
    """
    name: str
    type: str = "any"           # 仅作说明用，运行期不校验类型
    label: str = ""
    description: str = ""


# ==========================================================================
# 一条流程
# ==========================================================================
@dataclass
class Flow:
    """一条完整的业务流程，如 order_status_query（查订单状态）。

    结构对应 yaml：
        flows:
          order_status_query:
            name: 订单状态查询
            description: ...
            steps:
              - id: start
                type: start
                next: collect_order
              ...
    """
    id: str
    description: str = ""
    steps: list[FlowStep] = field(default_factory=list)
    slots: list[FlowSlot] = field(default_factory=list)
    name: str | None = None

    # ----------------------------------------------------------------------
    # 获取「开始」类型的步骤（每条流程有且只有一个 start 步骤）
    # 调用方：task/flowexecutor/flow_executor.py 启动任务时找入口
    # ----------------------------------------------------------------------
    def get_start_step(self) -> StartFlowStep:
        for step in self.steps:
            # isinstance 判断而不是比字符串，这样新增步骤类型时不用改这里
            if isinstance(step, StartFlowStep):
                return step
        # ※ 这里抛的是裸 Exception，属于可以改进的点（应自定义异常或无 yaml 校验兜底）；
        #   为保持与课程一致，暂不改行为。
        raise Exception("Flow not found")

    # ----------------------------------------------------------------------
    # 根据步骤 id 取步骤对象（FlowExecutor 每推进一步都要用它）
    # ※ 线性查找：流程步骤通常只有 5~10 个，不值得建索引
    # ----------------------------------------------------------------------
    def get_step_by_id(self, step_id) -> FlowStep:
        for step in self.steps:
            if step.id == step_id:
                return step
        raise Exception("step not found")


# ==========================================================================
# 全部流程的集合（yaml 解析后的总产物）
# ==========================================================================
@dataclass
class FlowCatalog:
    """一次 load 得到的全部配置。

    flows  dict[flow_id -> Flow]     供 FlowExecutor 按 id 取流程
    slots  dict[slot_name -> FlowSlot] 槽位全局索引

    ※ 注意 slots 是「全局合并」的：yaml 顶部定义的槽位对**所有流程**可见，
      流程里再写一遍只是引用，不会各自复制一份。
    """
    flows: dict[str, Flow] = field(default_factory=dict)
    slots: dict[str, FlowSlot] = field(default_factory=dict)

    # ----------------------------------------------------------------------
    # 根据流程 id 取流程
    # 调用方：task/command/command_processor.py（处理 start_flow 命令时）
    # ※ 这里用下标而不是 .get()，flow_id 不存在会抛 KeyError ——
    #   正常情况下 flow_id 已被 turn_plan_validator.py 校验过，走不到这里。
    # ----------------------------------------------------------------------
    def get_flow_by_id(self, flow_id) -> Flow:
        return self.flows[flow_id]
