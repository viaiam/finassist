"""补齐原有订单流程的最小样例；只新增缺失记录，不清库、不覆盖已有记录。"""
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

# 必须先读取中台配置，再导入会创建引擎的模块。
load_dotenv(Path(__file__).resolve().parent / '.env')
from app.database import SessionLocal
from app.models import User, Product, Order, OrderItem, LogisticsRecord, LogisticsTrace


def seed():
    now = datetime(2026, 11, 18, 10, 0)
    samples = [
        ('A1001', 'P1', '人体工学办公椅', '299.00', 'shipped', '已发货，正在运输中', '顺丰速运', 'SFTEST1001'),
        ('A1002', 'P2', '空气净化器', '1299.00', 'pending_shipment', '待发货，仓库正在备货', '', ''),
        ('C3003', 'P3', '桌面收纳盒', '89.00', 'completed', '订单已完成，包裹已签收', '中通快递', 'ZTTEST3003'),
    ]
    # 所有新增样例放在一个事务中；任一步失败会整体回滚。
    with SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.user_id == 'u1001'))
        if user is None:
            user = User(user_id='u1001', nickname='融知测试用户', level='normal',
                        mobile_masked='138****0001', created_at=now - timedelta(days=30))
            session.add(user)
            session.flush()
        for index, (order_id, product_id, title, price, status, description, company, tracking) in enumerate(samples):
            product = session.scalar(select(Product).where(Product.product_id == product_id))
            if product is None:
                product = Product(product_id=product_id, title=title,
                    description=f'{title}，仅用于现有客服流程的本地样例测试', price=Decimal(price),
                    stock_status='in_stock', cover_url=None, attributes_json={'用途': '样例测试'}, created_at=now)
                session.add(product)
                session.flush()
            order = session.scalar(select(Order).where(Order.order_id == order_id))
            if order is not None:
                if order.user_id != user.id:
                    raise RuntimeError(f'样例订单号 {order_id} 已被其他用户占用，停止以避免混淆')
                continue
            order = Order(order_id=order_id, user_id=user.id, status=status,
                status_desc=description, amount=Decimal(price), created_at=now - timedelta(days=index + 1),
                receiver_name='测试收件人', receiver_phone_masked='138****0001', receiver_address='本地测试地址（非真实配送地址）')
            session.add(order)
            session.flush()
            session.add(OrderItem(order_id=order.id, product_id=product.id, title_snapshot=title,
                                  quantity=1, price=Decimal(price)))
            # 待发货订单也提供一条状态记录，便于验证物流分支的自然语言回复。
            record = LogisticsRecord(order_id=order.id, logistics_company=company,
                tracking_number=tracking, status=status, status_desc=description, updated_at=now)
            session.add(record)
            session.flush()
            session.add(LogisticsTrace(logistics_record_id=record.id, trace_time=now, trace_desc=description))
    print('样例已准备：用户 u1001；订单 A1001 / A1002 / C3003；商品 P1 / P2 / P3')


if __name__ == '__main__':
    seed()
