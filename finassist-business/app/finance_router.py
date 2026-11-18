"""金融中台适配接口：沿用统一响应体，提供查询与投诉提交。"""
from datetime import date, timedelta
from typing import Literal
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Lock
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.finance_repository import (
    rows, customer_id, account, loan, engine, ensure_request_idempotency_table,
)

router = APIRouter(prefix='/finance', tags=['金融查询'])

# 与原金融资料接口保持一致：当前 MVP 在进程内缓存请求号，供演示重试幂等。
_ticket_requests: dict[str, tuple[dict, dict]] = {}
_ticket_lock = Lock()


class SupportTicketRequest(BaseModel):
    """投诉工单输入；客户身份取自会话 sender_id，不让模型代填。"""
    model_config = ConfigDict(str_strip_whitespace=True)
    request_no: str = Field(min_length=1, max_length=64)
    customer_no: str = Field(min_length=1, max_length=64)
    ticket_type: Literal['账户服务', '交易问题', '贷款服务', '银行卡服务', '其他']
    ticket_title: str = Field(min_length=1, max_length=128)
    ticket_content: str = Field(min_length=1, max_length=4000)
    related_transaction_no: str | None = Field(default=None, max_length=64)


def wrap(data):
    return {'code': 0, 'message': 'ok', 'data': data}


@router.get('/demo-customer')
def demo_customer():
    # 选择同时有账户、贷款和还款计划的客户，确保演示对象均有真实样例数据。
    found = rows('''SELECT c.customer_no FROM customer c
        WHERE EXISTS (SELECT 1 FROM bank_account a WHERE a.customer_id=c.id)
        AND EXISTS (SELECT 1 FROM loan_contract l JOIN repayment_schedule r ON r.contract_id=l.id
                    WHERE l.customer_id=c.id) ORDER BY c.id LIMIT 1''')
    if not found:
        raise HTTPException(404, '尚未准备金融样例客户。')
    return wrap(found[0])


@router.get('/customers/{customer_no}/objects')
def objects(customer_no: str):
    customer = customer_id(customer_no)
    accounts = rows('''SELECT account_no, currency_code, account_type, account_status,
        balance_amount, available_amount, frozen_amount FROM bank_account
        WHERE customer_id=:customer ORDER BY id LIMIT 20''', customer=customer)
    loans = rows('''SELECT loan_no, contract_status, principal_amount,
        outstanding_principal_amount, currency_code FROM loan_contract
        WHERE customer_id=:customer ORDER BY id LIMIT 20''', customer=customer)
    cards = rows('''SELECT CONCAT(LEFT(b.card_no,4),'********',RIGHT(b.card_no,4)) AS card_no_masked,
        b.card_type, b.card_status, a.account_no FROM bank_card b
        JOIN bank_account a ON a.id=b.account_id WHERE b.customer_id=:customer
        ORDER BY b.id LIMIT 20''', customer=customer)
    transactions = rows('''SELECT t.transaction_no, t.transaction_type, t.transaction_status,
        t.currency_code, t.transaction_amount, t.transaction_at, t.counterparty_name,
        COALESCE(f.account_no, target.account_no) AS account_no
        FROM account_transaction t
        LEFT JOIN bank_account f ON f.id=t.from_account_id
        LEFT JOIN bank_account target ON target.id=t.to_account_id
        WHERE t.customer_id=:customer ORDER BY t.transaction_at DESC, t.id DESC LIMIT 20''',
        customer=customer)
    return wrap({'customer_no': customer_no, 'accounts': accounts, 'loans': loans,
                 'cards': cards, 'transactions': transactions})


@router.get('/customers/{customer_no}/accounts/{account_no}')
def balance(customer_no: str, account_no: str):
    data = account(customer_no, account_no)
    data.pop('id')
    return wrap(data)


@router.get('/customers/{customer_no}/accounts/{account_no}/transactions')
def transactions(customer_no: str, account_no: str, transaction_date: date | None = None):
    target = account(customer_no, account_no)
    # 带日期时按自然日查询；无日期时返回最近 20 条，不把截断列表称为全部流水。
    sql = '''SELECT transaction_no, transaction_type, transaction_status, currency_code,
        transaction_amount, fee_amount, transaction_at, counterparty_name,
        CASE WHEN from_account_id=:account THEN '支出' ELSE '收入' END AS direction
        FROM account_transaction WHERE customer_id=:customer
        AND (from_account_id=:account OR to_account_id=:account)'''
    params = {'customer': customer_id(customer_no), 'account': target['id']}
    if transaction_date:
        sql += ' AND transaction_at>=:start AND transaction_at<:end'
        params.update(start=transaction_date, end=transaction_date + timedelta(days=1))
    data = rows(sql + ' ORDER BY transaction_at DESC, id DESC LIMIT 21', **params)
    return wrap({'account_no': target['account_no'], 'transactions': data[:20],
                 'has_more': len(data)>20, 'limit': 20, 'date': transaction_date})


@router.get('/customers/{customer_no}/loans/{loan_no}')
def loan_status(customer_no: str, loan_no: str):
    data = loan(customer_no, loan_no)
    data.pop('id')
    return wrap(data)


@router.get('/customers/{customer_no}/loans/{loan_no}/repayments')
def repayments(customer_no: str, loan_no: str):
    target = loan(customer_no, loan_no)
    data = rows('''SELECT period_no, due_date, currency_code, principal_amount,
        interest_amount, fee_amount, total_amount, schedule_status
        FROM repayment_schedule WHERE contract_id=:contract AND customer_id=:customer
        AND schedule_version=(SELECT MAX(schedule_version) FROM repayment_schedule WHERE contract_id=:contract)
        ORDER BY period_no LIMIT 61''', contract=target['id'], customer=customer_id(customer_no))
    return wrap({'loan_no': loan_no, 'repayments': data[:60], 'has_more': len(data)>60})


@router.get('/products')
def products(kind: Literal['loan', 'wealth'] = 'wealth', code: str | None = None):
    # 表名只能来自服务端白名单；产品编号仍使用参数绑定。
    fields = {
        'loan': 'p.loan_type, p.min_amount, p.max_amount, p.min_term_months, p.max_term_months, p.annual_interest_rate, p.repayment_method',
        'wealth': 'p.min_purchase_amount, p.expected_yield_rate, p.operation_mode, p.redeem_rule',
    }
    table = 'loan_product' if kind == 'loan' else 'wealth_product'
    sql = f'''SELECT p.product_code, p.product_name, p.currency_code, p.product_status,
        r.risk_level_name, {fields[kind]} FROM {table} p
        JOIN dim_risk_level r ON r.id=p.risk_level_id WHERE 1=1'''
    params = {}
    if code:
        sql += ' AND p.product_code=:code'
        params['code'] = code
    found = rows(sql + ' ORDER BY p.id LIMIT 20', **params)
    return wrap({'kind': kind, 'products': found, 'limit': 20,
                 'notice': '合成样例产品；利率字段为小数，0.03 表示 3%。理财预期收益不代表承诺收益，不构成个性化投资建议。'})


@router.post('/support/tickets')
def create_support_ticket(body: SupportTicketRequest):
    """创建投诉工单和初审任务，流水号只允许关联当前客户名下记录。"""
    values = body.model_dump()
    request_hash = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode('utf-8')
    ).hexdigest()
    with _ticket_lock:
        ensure_request_idempotency_table()
        cached = _ticket_requests.get(body.request_no)
        if cached:
            if cached[0] != values:
                raise HTTPException(409, '请求编号已用于其他工单内容。')
            return wrap(cached[1])
        saved = rows('''SELECT request_hash, response_json FROM finassist_request_idempotency
            WHERE scope='support_ticket' AND request_no=:request_no''', request_no=body.request_no)
        if saved:
            if saved[0]['request_hash'] != request_hash:
                raise HTTPException(409, '请求编号已用于其他工单内容。')
            response = json.loads(saved[0]['response_json'])
            _ticket_requests[body.request_no] = (values, response)
            return wrap(response)

        customer = customer_id(body.customer_no)
        transaction_id = None
        related_type = 'none'
        if body.related_transaction_no and body.related_transaction_no.strip().lower() not in ('无', '没有', '不涉及'):
            transaction = rows('''SELECT id FROM account_transaction
                WHERE transaction_no=:number AND customer_id=:customer''',
                number=body.related_transaction_no.strip(), customer=customer)
            if not transaction:
                raise HTTPException(404, '未找到该客户名下的交易流水，请核对流水号或填写“无”。')
            transaction_id = transaction[0]['id']
            related_type = 'account_transaction'

        # 与样例业务服务统一使用上海本地时间存 DATETIME。
        now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
        ticket_no = 'TKT' + now.strftime('%Y%m%d%H%M%S%f')
        workflow_no = 'WFI' + uuid4().hex
        task_no = 'WFT' + uuid4().hex
        response = {'ticket_no': ticket_no, 'ticket_status': 'submitted'}
        try:
            with engine.begin() as connection:
                channel = connection.execute(text(
                    "SELECT id FROM dim_channel WHERE channel_code='MOBILE_BANK' LIMIT 1"
                )).mappings().first()
                if not channel:
                    raise HTTPException(503, '金融工单渠道尚未配置。')
                result = connection.execute(text('''INSERT INTO support_ticket (
                    ticket_no, customer_id, channel_id, assignee_id, ticket_type,
                    related_type, related_id, ticket_title, ticket_content,
                    ticket_status, handle_result, submitted_at, created_at, updated_at
                ) VALUES (:ticket_no, :customer, :channel, NULL, :ticket_type,
                    :related_type, :related_id, :title, :content, 'submitted', '',
                    :now, :now, :now)'''), {
                    'ticket_no': ticket_no, 'customer': customer, 'channel': channel['id'],
                    'ticket_type': body.ticket_type, 'related_type': related_type,
                    'related_id': transaction_id, 'title': body.ticket_title,
                    'content': body.ticket_content, 'now': now,
                })
                ticket_id = result.lastrowid
                connection.execute(text('''INSERT INTO workflow_instance (
                    instance_no, workflow_type, related_type, related_id,
                    initiator_type, initiator_no, instance_status,
                    started_at, created_at, updated_at
                ) VALUES (:instance_no, 'support_ticket', 'support_ticket', :related_id,
                    'customer', :customer_no, 'running', :now, :now, :now)'''), {
                    'instance_no': workflow_no, 'related_id': ticket_id,
                    'customer_no': body.customer_no, 'now': now,
                })
                instance_id = connection.execute(text(
                    'SELECT id FROM workflow_instance WHERE instance_no=:number'
                ), {'number': workflow_no}).scalar_one()
                connection.execute(text('''INSERT INTO workflow_task (
                    task_no, instance_id, node_code, node_name, assignee_id,
                    task_status, assigned_at, created_at, updated_at
                ) VALUES (:task_no, :instance_id, 'initial_review', '初审', NULL,
                    'pending', :now, :now, :now)'''), {
                    'task_no': task_no, 'instance_id': instance_id, 'now': now,
                })
                # 工单、待办和请求幂等结果同事务提交，避免故障重试生成重复工单。
                connection.execute(text('''INSERT INTO finassist_request_idempotency
                    (scope, request_no, request_hash, response_json, created_at)
                    VALUES ('support_ticket', :request_no, :request_hash, :response_json, :created_at)'''), {
                    'request_no': body.request_no, 'request_hash': request_hash,
                    'response_json': json.dumps(response, ensure_ascii=False), 'created_at': now,
                })
        except IntegrityError as exc:
            # 多进程并发请求由数据库唯一键仲裁，失败事务里的工单会一起回滚。
            saved = rows('''SELECT request_hash, response_json FROM finassist_request_idempotency
                WHERE scope='support_ticket' AND request_no=:request_no''', request_no=body.request_no)
            if saved:
                if saved[0]['request_hash'] != request_hash:
                    raise HTTPException(409, '请求编号已用于其他工单内容。') from exc
                response = json.loads(saved[0]['response_json'])
            else:
                raise HTTPException(503, '工单提交失败，请稍后重试。') from exc
        except HTTPException:
            raise
        except SQLAlchemyError as exc:
            raise HTTPException(503, '工单提交失败，请稍后重试。') from exc

        _ticket_requests[body.request_no] = (values, response)
        return wrap(response)


@router.get('/customers/{customer_no}/support/tickets/{ticket_no}')
def get_support_ticket(customer_no: str, ticket_no: str):
    """仅返回当前客户自己的工单状态和关联交易流水。"""
    customer = customer_id(customer_no)
    found = rows('''SELECT t.ticket_no, t.ticket_type, t.ticket_title, t.ticket_content,
        t.ticket_status, t.handle_result, t.submitted_at, tx.transaction_no,
        CASE wi.instance_status WHEN 'running' THEN '待初审'
             WHEN 'completed' THEN '已处理' ELSE wi.instance_status END AS process_status
        FROM support_ticket t LEFT JOIN account_transaction tx
        ON t.related_type='account_transaction' AND tx.id=t.related_id
        LEFT JOIN workflow_instance wi
        ON wi.related_type='support_ticket' AND wi.related_id=t.id
        WHERE t.ticket_no=:ticket_no AND t.customer_id=:customer''',
        ticket_no=ticket_no, customer=customer)
    if not found:
        raise HTTPException(404, '未找到当前客户的该工单。')
    return wrap(found[0])
