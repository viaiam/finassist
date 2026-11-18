"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:注册所有 action。
          两种方式并存：
            register_action         手写注册，一行一个，注册了哪些一眼看清（3 个以内推荐）
            register_custom_action  包扫描自动注册，只认 custom 目录下 Action 的子类
          几十个 action 之后手写就是纯重复劳动，所以 builder 里默认走包扫描。
"""
import importlib
import inspect
import pkgutil

from finassist.task.action.base import Action
from finassist.task.action.custom.logistics_tracking import LogisticsTrackingAction
from finassist.task.action.custom.order_status_query import OrderStatusAction
from finassist.task.action.custom.recommend import RecommendProductsAction
from finassist.task.action.registry import ActionRegistry

# custom 包名写死成字符串，扫描时要用它做 import
CUSTOM_PACKAGE = "finassist.task.action.custom"


def register_action(action_registry: ActionRegistry):
    action_registry.register(LogisticsTrackingAction())
    action_registry.register(OrderStatusAction())
    # yaml 里 similar_product_recommendation 用到了 action_recommend_similar_products，
    # 课程还留了 todo，这里先注册一个占位实现，免得那条流程走到 action 就报错
    action_registry.register(RecommendProductsAction())


def register_custom_action(action_registry: ActionRegistry):
    """扫描 custom 包，把里面所有 Action 子类自动注册。

    规则（三条都得满足）：
      1 是 Action 的子类，且不是 Action 自己
      2 类的定义写在这个模块里（排除 import 进来的类，否则同一个类会被注册多次）
      3 模块不是子包（custom/abc 这种目录跳过，避免把工具类扫进来）
    """
    package = importlib.import_module(CUSTOM_PACKAGE)

    # iter_modules 只列一层：给的是 (module_finder, name, is_pkg)
    for _, module_name, is_package in pkgutil.iter_modules(
        package.__path__,
        prefix=f"{package.__name__}.",
    ):
        if is_package:
            continue

        module = importlib.import_module(module_name)
        for _, action_class in inspect.getmembers(module, inspect.isclass):
            if not issubclass(action_class, Action) or action_class is Action:
                continue
            # 只认"定义在本文件"的类：from ...base import Action 这类导入会被这一步挡掉
            # 跳过只承载公共实现、尚未声明动作名的父类。
            if not action_class.name:
                continue
            if action_class.__module__ != module.__name__:
                continue
            action_registry.register(action_class())
