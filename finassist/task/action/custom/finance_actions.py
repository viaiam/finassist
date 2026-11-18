"""金融查询与投诉动作：沿用槽位流程，金融查询事实由中台返回。"""
from datetime import date
from decimal import Decimal
from urllib.parse import quote
from finassist.finance_client import get_finance, post_finance, customer_path, FinanceQueryError
from finassist.task.action.base import Action, ActionResult


def money(value, currency='CNY'):
    return f'{Decimal(str(value)):.2f} {currency}'


def status(value):
    return {'active':'正常', 'frozen':'冻结', 'closed':'已关闭', 'normal':'正常',
            'settled':'已结清', 'overdue':'逾期', 'disbursed':'已放款', 'signed':'已签约',
            'pending':'待还款', 'paid':'已还款', 'success':'成功', 'failed':'失败',
            'processing':'处理中', 'partially_paid':'部分还款'}.get(value, value)


async def query(state, kind):
    slots = state.tasks.active.slots
    base = customer_path(state.sender_id)
    if kind in ('balance', 'transactions'):
        number = quote(str(slots['account_no']), safe='')
        path = f'{base}/accounts/{number}'
    else:
        number = quote(str(slots['loan_no']), safe='')
        path = f'{base}/loans/{number}'
    if kind == 'balance':
        data = await get_finance(path)
        return (f"账户 {data['account_no']}，状态：{status(data['account_status'])}。\n"
                f"账面余额：{money(data['balance_amount'], data['currency_code'])}；"
                f"可用余额：{money(data['available_amount'], data['currency_code'])}；"
                f"冻结金额：{money(data['frozen_amount'], data['currency_code'])}。")
    if kind == 'transactions':
        day = str(slots['transaction_date']).strip()
        params = {}
        if day != '最近':
            try:
                params['transaction_date'] = date.fromisoformat(day).isoformat()
            except ValueError as exc:
                raise FinanceQueryError('日期格式不正确，请重新查询并提供 YYYY-MM-DD 日期，或填写“最近”。') from exc
        data = await get_finance(path + '/transactions', params)
        if not data['transactions']:
            return '所选日期未查到该账户的交易记录。'
        lines = [f"{row['transaction_at']}｜{row['transaction_no']}｜{row['direction']} "
                 f"{money(row['transaction_amount'], row['currency_code'])}｜{status(row['transaction_status'])}"
                 for row in data['transactions']]
        return '查询结果（按时间倒序，最多 20 条）：\n' + '\n'.join(lines) + ('\n还有更多记录，请缩小日期范围。' if data['has_more'] else '')
    if kind == 'loan':
        data = await get_finance(path)
        rate = Decimal(str(data['annual_interest_rate'])) * 100
        return (f"贷款 {data['loan_no']}（{data['product_name']}），状态：{status(data['contract_status'])}。\n"
                f"合同本金：{money(data['principal_amount'], data['currency_code'])}；"
                f"未还本金：{money(data['outstanding_principal_amount'], data['currency_code'])}；"
                f"年利率：{rate:g}%；期限：{data['term_months']} 个月。")
    data = await get_finance(path + '/repayments')
    if not data['repayments']:
        return '这笔贷款暂未生成还款计划。'
    return '最新版本还款计划（最多 60 期）：\n' + '\n'.join(
        f"第 {row['period_no']} 期｜{row['due_date']}｜应还 {money(row['total_amount'], row['currency_code'])}｜{status(row['schedule_status'])}"
        for row in data['repayments'])


class FinancialAction(Action):
    """统一失败提示；查询失败不伪造余额，也不向用户暴露底层数据库异常。"""
    kind = ''

    async def run(self, state):
        try:
            result = await query(state, self.kind)
        except FinanceQueryError as exc:
            result = str(exc)
        return ActionResult(slots_update={'finance_result': result})


class AccountBalanceAction(FinancialAction):
    name = 'action_account_balance'
    kind = 'balance'


class TransactionQueryAction(FinancialAction):
    name = 'action_transactions'
    kind = 'transactions'


class LoanStatusAction(FinancialAction):
    name = 'action_loan_status'
    kind = 'loan'


class RepaymentQueryAction(FinancialAction):
    name = 'action_repayments'
    kind = 'repayments'


class ComplaintTicketAction(Action):
    """提交当前样例客户的投诉，并用任务 ID 作为重试幂等键。"""
    name = 'action_complaint_ticket'

    async def run(self, state):
        slots = state.tasks.active.slots
        transaction_no = str(slots['related_transaction_no']).strip()
        if transaction_no.lower() in ('无', '没有', '不涉及', 'none'):
            transaction_no = None
        try:
            data = await post_finance('/finance/support/tickets', {
                'request_no': f"complaint-{state.tasks.active.task_id}",
                'customer_no': state.sender_id,
                'ticket_type': slots['ticket_type'],
                'ticket_title': f"金融业务投诉：{slots['ticket_type']}",
                'ticket_content': slots['ticket_description'],
                'related_transaction_no': transaction_no,
            })
            result = (f"投诉已提交，工单编号：{data['ticket_no']}；当前状态：待受理。"
                      '请保存工单编号。目前仅支持提交，尚未接入人工处理工作台。')
        except FinanceQueryError as exc:
            result = str(exc)
        return ActionResult(slots_update={'ticket_result': result})


class TicketStatusAction(Action):
    """查询当前客户自己的投诉工单状态。"""
    name = 'action_ticket_status'

    async def run(self, state):
        ticket_no = quote(str(state.tasks.active.slots['ticket_no']), safe='')
        try:
            data = await get_finance(
                f'{customer_path(state.sender_id)}/support/tickets/{ticket_no}')
            result = (f"工单 {data['ticket_no']}：{data['ticket_status']}；"
                      f"处理进度：{data.get('process_status') or '暂无'}。")
        except FinanceQueryError as exc:
            result = str(exc)
        return ActionResult(slots_update={'ticket_result': result})
