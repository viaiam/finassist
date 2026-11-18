"""
本地假中台（仅开发联调用，不属于项目代码）。

真实中台没起来时，用它顶上 18081 端口，让订单查询 / 物流查询 / 商品查询
这三条远程调用链路能跑通。

启动：
    .venv\\Scripts\\python.exe mock_business_server.py

覆盖的接口：
    GET /orders/{order_number}/status
    GET /orders/{order_number}/logistics
    GET /orders/{order_number}
    GET /products/{product_id}
"""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 18081

ORDERS = {
    "A1001": {
        "order_number": "A1001",
        "status": "已发货",
        "status_desc": "预计明天 18:00 前送达",
        "amount": "299.00",
        "created_at": "2026-11-15 10:20:00",
        "items": [{"product_id": "P1", "title": "人体工学办公椅", "count": 1}],
    },
    "A1002": {
        "order_number": "A1002",
        "status": "待付款",
        "status_desc": "请在 30 分钟内完成支付，超时订单自动取消",
        "amount": "1299.00",
        "created_at": "2026-11-16 18:00:00",
        "items": [{"product_id": "P2", "title": "空气净化器", "count": 1}],
    },
    "C3003": {
        "order_number": "C3003",
        "status": "已签收",
        "status_desc": "已签收，7 天内可申请无理由退货",
        "amount": "89.00",
        "created_at": "2026-11-10 09:00:00",
        "items": [{"product_id": "P3", "title": "桌面收纳盒", "count": 1}],
    },
}

LOGISTICS = {
    "A1001": {
        "logistics_company": "顺丰速运",
        "tracking_number": "SF1234567890",
        "status_desc": "运输中，预计明天 18:00 前送达",
    },
    "A1002": {
        "logistics_company": "",
        "tracking_number": "",
        "status_desc": "订单还未发货",
    },
    "C3003": {
        "logistics_company": "中通快递",
        "tracking_number": "ZT9876543210",
        "status_desc": "已签收",
    },
}

PRODUCTS = {
    "P1": {
        "product_id": "P1",
        "title": "人体工学办公椅",
        "price": "299.00",
        "stock": 42,
        "selling_points": ["腰托可调", "网面透气", "承重 150kg"],
    },
    "P2": {
        "product_id": "P2",
        "title": "空气净化器",
        "price": "1299.00",
        "stock": 8,
        "selling_points": ["CADR 500", "静音 28dB", "滤芯可水洗"],
    },
    "P3": {
        "product_id": "P3",
        "title": "桌面收纳盒",
        "price": "89.00",
        "stock": 120,
        "selling_points": ["可叠放", "环保ABS"],
    },
}

ROUTES = [
    (re.compile(r"^/orders/([^/]+)/status$"), "order_status"),
    (re.compile(r"^/orders/([^/]+)/logistics$"), "order_logistics"),
    (re.compile(r"^/orders/([^/]+)$"), "order_detail"),
    (re.compile(r"^/products/([^/]+)$"), "product_detail"),
]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status_code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        for pattern, kind in ROUTES:
            match = pattern.match(path)
            if not match:
                continue
            key = match.group(1)

            if kind == "order_status":
                if key not in ORDERS:
                    return self._send(404, {"code": 404, "message": f"订单 {key} 不存在"})
                return self._send(200, {"code": 0, "data": ORDERS[key]})

            if kind == "order_logistics":
                if key not in LOGISTICS:
                    return self._send(404, {"code": 404, "message": f"订单 {key} 不存在"})
                return self._send(200, {"code": 0, "data": LOGISTICS[key]})

            if kind == "order_detail":
                if key not in ORDERS:
                    return self._send(404, {"code": 404, "message": f"订单 {key} 不存在"})
                return self._send(200, {"code": 0, "data": ORDERS[key]})

            if kind == "product_detail":
                if key not in PRODUCTS:
                    return self._send(404, {"code": 404, "message": f"商品 {key} 不存在"})
                return self._send(200, {"code": 0, "data": PRODUCTS[key]})

        self._send(404, {"code": 404, "message": f"没有这个接口：{path}"})

    def log_message(self, fmt, *args):
        print(f"[mock-business] {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[mock-business] listening on http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
