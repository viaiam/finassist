"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:查订单状态。远程调用中台接口，把结果装成 ActionResult 交回 FlowExecutor
"""
from finassist.conf.config import settings
from finassist.domain.state import DialogueState
from finassist.task.action.base import Action, ActionResult
from finassist.utils import httpx_client


class OrderStatusAction(Action):
    # 必须和 yaml 里 action 步骤的 action 字段一致
    name = "action_lookup_order_status"

    async def run(self, state: DialogueState) -> ActionResult:
        # 1 从当前任务槽位里拿订单号（collect 步骤已经保证它填上了）
        order_number = state.tasks.active.slots.get("order_number")

        # 2 拼路径 + 远程调用
        url = f"{settings.business_api_base_url}/orders/{order_number}/status"
        response = await httpx_client.http_client.get(url)
        # 中台 4xx/5xx 直接抛，别让 None 一路传到模板里渲染成"当前状态是：。"
        response.raise_for_status()

        # 3 取 data；万一没有 data 字段，用空字典兜住
        data = response.json().get("data") or {}

        return ActionResult(
            slots_update={
                "order_status": data.get("status", "未知"),
                "order_summary": data.get("status_desc", ""),
            }
        )
