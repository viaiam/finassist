from __future__ import annotations

from fastapi import FastAPI

from app.api import router


openapi_tags = [
    {
        "name": "系统",
        "description": "服务可用性与基础检查接口。",
    },
    {
        "name": "用户",
        "description": "查询用户相关的订单列表和商品列表。",
    },
    {
        "name": "订单",
        "description": "订单详情、订单状态、物流信息，以及订单相关操作请求。",
    },
    {
        "name": "商品",
        "description": "商品详情查询接口。",
    },
]


app = FastAPI(
    title="FinAssist 业务中台服务",
    version="0.1.0",
    description="为 FinAssist 客服项目提供订单、物流、商品与订单操作能力的示例业务服务。",
    openapi_tags=openapi_tags,
)

app.include_router(router)

# 保留原有接口，只追加金融查询适配层。
from app.finance_router import router as finance_router
app.include_router(finance_router)
