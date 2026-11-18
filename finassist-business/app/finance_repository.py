"""金融查询数据层：复用样例库，只读访问，所有用户输入均绑定为 SQL 参数。"""
import os
from threading import Lock
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

# 使用独立配置，不把金融表与原订单表混在一个数据库中。
engine = create_engine(os.environ['FINASSIST_FINANCE_DATABASE_URL'], pool_pre_ping=True)
_idempotency_table_lock = Lock()
_idempotency_table_ready = False


def ensure_request_idempotency_table():
    """按需创建金融写接口的幂等表，避免改动原始金融资料脚本。"""
    global _idempotency_table_ready
    if _idempotency_table_ready:
        return
    with _idempotency_table_lock:
        if _idempotency_table_ready:
            return
        try:
            with engine.begin() as connection:
                connection.execute(text('''CREATE TABLE IF NOT EXISTS finassist_request_idempotency (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    scope VARCHAR(64) NOT NULL,
                    request_no VARCHAR(128) NOT NULL,
                    request_hash CHAR(64) NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    UNIQUE KEY uk_finassist_request (scope, request_no)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'''))
            _idempotency_table_ready = True
        except SQLAlchemyError as exc:
            raise HTTPException(503, '金融写服务尚未准备好，请稍后重试。') from exc


def rows(sql, **params):
    try:
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(text(sql), params).mappings()]
    except SQLAlchemyError as exc:
        raise HTTPException(503, '金融数据服务暂不可用，请稍后重试。') from exc


def customer_id(customer_no):
    found = rows('SELECT id FROM customer WHERE customer_no=:number', number=customer_no)
    if not found:
        raise HTTPException(404, '客户编号不存在，请使用页面提供的样例客户编号。')
    return found[0]['id']


def account(customer_no, account_no):
    # 账户查询也兼容完整银行卡号；掩码卡号不能作为唯一定位依据。
    found = rows('''SELECT DISTINCT a.account_no, a.currency_code, a.account_type,
        a.account_status, a.balance_amount, a.available_amount, a.frozen_amount, a.id
        FROM bank_account a LEFT JOIN bank_card b ON b.account_id=a.id
        WHERE a.customer_id=:customer AND (a.account_no=:number OR
        (b.card_no=:number AND b.customer_id=:customer))''',
        customer=customer_id(customer_no), number=account_no)
    if not found:
        raise HTTPException(404, '未找到当前客户名下的账户，请核对编号或点击右侧账户卡片。')
    return found[0]


def loan(customer_no, loan_no):
    found = rows('''SELECT l.id, l.loan_no, l.contract_status, l.principal_amount,
        l.outstanding_principal_amount, l.annual_interest_rate, l.term_months,
        l.repayment_method, l.currency_code, p.product_name
        FROM loan_contract l JOIN loan_product p ON p.id=l.product_id
        WHERE l.customer_id=:customer AND l.loan_no=:number''',
        customer=customer_id(customer_no), number=loan_no)
    if not found:
        raise HTTPException(404, '未找到当前客户名下的贷款，请核对编号或点击右侧贷款卡片。')
    return found[0]
