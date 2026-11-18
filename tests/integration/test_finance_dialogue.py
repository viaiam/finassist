"""金融闭环验证：独立临时中台 + 真实样例库；--live-model 另测实际模型对话。"""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    # 只关闭本测试创建的中台进程，不干扰用户正在运行的服务。
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    os.environ['FINASSIST_BUSINESS_API_BASE_URL'] = base
    middle = ROOT / 'finassist-business'
    process = subprocess.Popen([str(middle / '.venv/Scripts/python.exe'), '-m', 'uvicorn',
        'app.app:app', '--env-file', str(middle / '.env'), '--host', '127.0.0.1', '--port', str(port),
        '--log-level', 'error'], cwd=middle, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('临时中台启动失败')
            try:
                with urllib.request.urlopen(base+'/finance/demo-customer', timeout=1) as response:
                    customer = json.load(response)['data']['customer_no']
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('临时中台启动超时')
        with urllib.request.urlopen(base+f'/finance/customers/{customer}/objects') as response:
            objects = json.load(response)['data']
        asyncio.run(check_engine(customer, objects))
        if '--live-model' in sys.argv:
            check_live(customer, objects)
    finally:
        process.terminate()
        process.wait(timeout=10)


async def check_engine(customer, objects):
    from finassist.engine.builder import build_engine
    from finassist.domain.state import DialogueState
    from finassist.domain.message import UserMessage, MessageType, MessageObject
    from finassist.prompts.models import TurnPlan
    from finassist.utils.httpx_client import init_http_client, close_http_client
    from finassist.knowledge.provider import BankCardProvider, LoanProductProvider, WealthProductProvider
    from finassist.task.action.custom.finance_actions import query
    from finassist.finance_client import FinanceQueryError

    engine = build_engine()
    state = DialogueState(sender_id=customer)
    # 确定性拦截模型伪造的查询结果和不存在的知识意图。
    forged = TurnPlan.from_dict({'task': {'commands': [
        {'command':'start_flow', 'flow':'account_balance'},
        {'command':'set_slots', 'slots':{'finance_result':'余额为一亿元'}}]},
        'knowledge':None, 'chitchat':None})
    assert not engine.turn_plan_validator.validate(forged, state, engine.flow_catalog).valid
    unknown = TurnPlan.from_dict({'task':None, 'knowledge':{'intents':['not-supported']}, 'chitchat':None})
    assert not engine.turn_plan_validator.validate(unknown, state, engine.flow_catalog).valid

    class PlannedTurn:
        current = None
        async def plan(self, **kwargs):
            return self.current
    planner = PlannedTurn()
    engine.turn_planner = planner

    async def turn(commands):
        planner.current = TurnPlan.from_dict({'task': {'commands':commands}, 'knowledge':None, 'chitchat':None})
        result = await engine.process_message(state, UserMessage(customer, str(uuid4()), MessageType.TEXT, text='金融流程测试'))
        return '\n'.join(message.text or '' for message in result.messages)

    start = lambda flow: {'command':'start_flow', 'flow':flow}
    fill = lambda **slots: {'command':'set_slots', 'slots':slots}
    init_http_client()
    try:
        account = objects['accounts'][0]['account_no']
        loan = objects['loans'][0]['loan_no']
        # 多轮收集：第一轮缺账户号，第二轮直接用对象消息填槽完成查询。
        assert '账户号' in await turn([start('account_balance')])
        result = await engine.process_message(state, UserMessage(customer, str(uuid4()), MessageType.OBJECT,
            object=MessageObject(type='account', id=account)))
        assert '可用余额' in '\n'.join(message.text or '' for message in result.messages)
        assert state.tasks.active is None
        # 日期与空结果：交易动作调用真实接口，不调用模型生成事实。
        result = await turn([start('transaction_query'), fill(account_no=account, transaction_date='1900-01-01')])
        assert '未查到' in result
        result = await turn([start('transaction_query'), fill(account_no=account, transaction_date='最近')])
        assert '交易记录' in result or '查询结果' in result
        result = await turn([start('transaction_query'), fill(account_no=account, transaction_date='not-a-date')])
        assert '日期格式不正确' in result
        # 切换和恢复：查询交易正等日期时去查贷款，再回到原有交易任务。
        await turn([start('transaction_query'), fill(account_no=account)])
        paused_id = state.tasks.active.task_id
        result = await turn([start('loan_status'), fill(loan_no=loan)])
        assert '年利率' in result and state.tasks.paused[0].task_id == paused_id
        await turn([{'command':'resume_task','task_id':paused_id}])
        assert state.tasks.active.flow_id == 'transaction_query'
        result = await turn([fill(transaction_date='最近')])
        assert state.tasks.active is None and not state.tasks.paused
        result = await turn([start('repayment_query'), fill(loan_no=loan)])
        assert '应还' in result
        # 投诉流程按轮收集类型、关联流水和描述，最终提交真实工单。
        result = await turn([start('complaint_ticket'), fill(ticket_type='交易问题')])
        assert '流水号' in result
        from finassist.domain.message import MessageObject
        transaction_no = objects.get('transactions', [{}])[0].get('transaction_no')
        if transaction_no:
            result = await engine.process_message(state, UserMessage(customer, str(uuid4()),
                MessageType.OBJECT, object=MessageObject(type='transaction', id=transaction_no,
                    attributes={'transaction_no': transaction_no})))
            result = '\n'.join(message.text or '' for message in result.messages)
        else:
            result = await turn([fill(related_transaction_no='无')])
        assert '描述具体问题' in result
        result = await turn([fill(ticket_description='测试交易未到账，请协助核查。')])
        assert '投诉已提交' in result and '工单编号：TKT' in result, result
        ticket_no = result.split('工单编号：', 1)[1].split('；', 1)[0]
        from finassist.finance_client import get_finance
        detail = await get_finance(f'/finance/customers/{customer}/support/tickets/{ticket_no}')
        assert detail['ticket_status'] == 'submitted'
        assert detail['ticket_title'].startswith('金融业务投诉')
        result = await turn([start('ticket_status_query'), fill(ticket_no=ticket_no)])
        assert '待初审' in result and ticket_no in result, result
        await turn([start('transaction_query')])
        active_id = state.tasks.active.task_id
        await turn([{'command':'cancel_task','task_id':active_id}])
        assert state.tasks.active is None
        # 用户输入无法查询别人的账户；错误返回为正常回复而非 HTTP 500。
        result = await turn([start('account_balance'), fill(account_no='not-owned')])
        assert '未找到当前客户名下' in result
        msg = UserMessage(customer, str(uuid4()), MessageType.TEXT, text='金融咨询')
        for provider in (BankCardProvider(), LoanProductProvider(), WealthProductProvider()):
            assert await provider.execute(state, msg)
        print('PASS: 真实数据动作、对象填槽、多轮日期、空结果、查询失败、任务切换/恢复/取消和知识取数')
    finally:
        await close_http_client()


def check_live(customer, objects):
    from fastapi.testclient import TestClient
    from finassist.api.app import app
    account = objects['accounts'][0]['account_no']
    loan = objects['loans'][0]['loan_no']
    # 使用真实客户编号以便隔离查询；记录测试前历史，确认本轮成功持久化。
    with TestClient(app) as client:
        before = client.get('/api/chat/history', params={'sender_id':customer}).json()['messages']
        questions = [(f'请查询账户 {account} 的余额', '可用余额'),
                     (f'查看贷款 {loan} 的还款计划', '应还'),
                     ('有哪些理财产品？请说明风险和起购金额。', None),
                     ('我要挂失信用卡，现在能办理吗？', None)]
        for text, expected in questions:
            response = client.post('/api/chat', json={'sender_id':customer, 'text':text, 'message_id':str(uuid4())})
            assert response.status_code == 200, response.text
            answer = '\n'.join(message.get('text') or '' for message in response.json()['messages'])
            assert answer
            if expected:
                assert expected in answer, answer
            if '挂失' in text:
                assert any(word in answer for word in ('暂未', '尚未', '不支持', '无法', '不能', '未接入')), answer
            print('LIVE', text, '=>', answer[:500], flush=True)
        after = client.get('/api/chat/history', params={'sender_id':customer}).json()['messages']
        assert len(after) > len(before)
    print('PASS: 真实模型意图识别、金融查询、产品回答、能力边界和会话持久化')


if __name__ == '__main__':
    main()
