"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:查物流进度。和查订单状态一个套路：取槽位 → 拼路径 → 远程调用 → 装槽位
"""
from finassist.conf.config import settings
from finassist.domain.state import DialogueState
from finassist.task.action.base import Action, ActionResult
from finassist.utils import httpx_client


class LogisticsTrackingAction(Action):
    name = "action_lookup_logistics"

    async def run(self, state: DialogueState) -> ActionResult:
        # 1 需要订单号
        order_number = state.tasks.active.slots.get("order_number")

        # 2 远程调用
        url = f"{settings.business_api_base_url}/orders/{order_number}/logistics"
        response = await httpx_client.http_client.get(url)
        response.raise_for_status()

        # 3 中台没返回 data 时用空字典兜住，否则下面的 .get 会 AttributeError
        data = response.json().get("data") or {}

        return ActionResult(
            slots_update={
                "logistics_company": data.get("logistics_company", "未知"),
                "tracking_number": data.get("tracking_number", "未知"),
                "logistics_status": data.get("status_desc", "未知"),
            }
        )
