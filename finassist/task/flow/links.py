"""
task/flow/links.py —— 步骤之间的「连线」（决定下一步跳到哪）

■ 它是什么
    YAML 里每个步骤都可以写 next，表示「这一步做完，下一步去哪」。
    next 支持两种写法，对应本文件的三个类：

        next: step_2                                  → StaticLink        （写死目标）
        next:                                         → ConditionalLink   （按条件挑）
          - if: slots.order_status == "已发货"          condition + target
            target: step_ok
          - if: slots.order_status == "待付款"
            target: step_fail
          - target: step_default                      → FallbackLink      （兜底，无 condition）

    FallbackLink 不写 if，就相当于 switch 里的 default 分支：谁都不匹配时走它。

■ 在调用链中的位置
    task/flow/steps.py::FlowStep._build_links()  解析 yaml 的 next 字段，产出这些对象
                ↓
    task/flowexecutor/flow_executor.py::_run_next_step()  遍历列表，挑出真正要跳的那一条
                ↓
    eval(link.condition, {"__builtins__": {}}, {"slots": task.slots})   求值条件表达式

  ※ 三点注意事项：
    1) 继承关系是 FlowStepLink 做基类，所以 _run_next_step 里可以统一按
       基类类型遍历，再用 isinstance 分辨是条件型还是兜底型；
    2) StaticLink / FallbackLink 用 pass 空继承，只为「有类型」，
       方便 isinstance 判断、也方便 IDE 提示，没有额外字段；
    3) eval 已经禁用了内置函数（__builtins__ 传空字典），
       条件表达式里只能引用 slots，写别的名字会 NameError —— 这是刻意的安全限制，
       但也意味着条件里不能写 len()、int() 这类函数。
"""
from dataclasses import dataclass


# ==========================================================================
# 基类：所有连线都至少有「目标步骤 id」
# ==========================================================================
@dataclass
class FlowStepLink:
    """连线的公共部分。target 是目标步骤的 id（对应 yaml 里步骤的 id 字段）。"""
    target: str


# ==========================================================================
# 静态连线：无条件，直接跳到 target
# ==========================================================================
@dataclass
class StaticLink(FlowStepLink):
    """yaml 里直接写 next: 某个步骤id 时的产物，最常见的一种。"""
    pass


# ==========================================================================
# 条件连线：满足 condition 才走这条
# ==========================================================================
@dataclass
class ConditionalLink(FlowStepLink):
    """yaml 里写了 if 的连线。

    condition 是一段 Python 表达式字符串，由 FlowExecutor 用 eval 求值，
    可用的名字只有 slots。例如：
        slots.order_status == "已发货"
        slots.refund_reason is not None
    ※ 注意这里存的是**字符串**，不是编译后的表达式，也不做任何校验 ——
      表达式写错要等到运行时走到这一步才会暴露。
    """
    condition: str


# ==========================================================================
# 兜底连线：所有条件都不满足时走它
# ==========================================================================
@dataclass
class FallbackLink(FlowStepLink):
    """yaml 里没写 if 的那条（放在最后）。相当于 switch 的 default 分支。"""
    pass
