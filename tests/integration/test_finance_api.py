"""金融适配层的只读集成测试，使用已生成的样例库。"""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'finassist-business'))
from dotenv import load_dotenv
load_dotenv(ROOT / 'finassist-business/.env')
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.finance_router import router


class FinanceApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router)
        cls.client = TestClient(app)
        cls.customer = cls.client.get('/finance/demo-customer').json()['data']['customer_no']
        cls.base = f'/finance/customers/{cls.customer}'
        cls.objects = cls.client.get(cls.base + '/objects').json()['data']

    def test_real_accounts_and_masked_cards(self):
        self.assertTrue(self.objects['accounts'])
        self.assertTrue(self.objects['loans'])
        self.assertIn('transactions', self.objects)
        self.assertTrue(self.objects['transactions'])
        for card in self.objects['cards']:
            self.assertIn('*', card['card_no_masked'])
            self.assertNotIn('card_no', card)
        account = self.objects['accounts'][0]['account_no']
        response = self.client.get(self.base + f'/accounts/{account}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('available_amount', response.json()['data'])

    def test_customer_scope_and_unknown_identity(self):
        self.assertEqual(self.client.get('/finance/customers/u1001/objects').status_code, 404)
        self.assertEqual(self.client.get(self.base + '/accounts/not-owned').status_code, 404)
        self.assertEqual(self.client.get(self.base + "/accounts/' OR 1=1 --").status_code, 404)

    def test_real_other_customer_account_is_hidden(self):
        from app.finance_repository import rows, customer_id
        other = rows('SELECT account_no FROM bank_account WHERE customer_id<>:customer LIMIT 1',
                     customer=customer_id(self.customer))[0]['account_no']
        response = self.client.get(self.base + f'/accounts/{other}')
        self.assertEqual(response.status_code, 404)

    def test_dates_and_empty_day(self):
        account = self.objects['accounts'][0]['account_no']
        endpoint = self.base + f'/accounts/{account}/transactions'
        self.assertEqual(self.client.get(endpoint, params={'transaction_date': 'bad-date'}).status_code, 422)
        result = self.client.get(endpoint, params={'transaction_date': '1900-01-01'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['data']['transactions'], [])

    def test_loans_repayments_and_products(self):
        loan = self.objects['loans'][0]['loan_no']
        self.assertEqual(self.client.get(self.base + f'/loans/{loan}').status_code, 200)
        data = self.client.get(self.base + f'/loans/{loan}/repayments').json()['data']
        self.assertTrue(data['repayments'])
        for kind in ('loan', 'wealth'):
            result = self.client.get('/finance/products', params={'kind': kind}).json()['data']
            self.assertTrue(result['products'])
        self.assertEqual(self.client.get('/finance/products', params={'kind': 'fake'}).status_code, 422)

    def test_support_ticket_submission_is_scoped_and_idempotent(self):
        from app.finance_repository import rows, customer_id
        transaction = rows('''SELECT transaction_no FROM account_transaction
            WHERE customer_id=:customer LIMIT 1''', customer=customer_id(self.customer))[0]['transaction_no']
        body = {'request_no': 'test-' + __import__('uuid').uuid4().hex,
                'customer_no': self.customer, 'ticket_type': '交易问题',
                'ticket_title': '测试交易问题', 'ticket_content': '测试投诉描述',
                'related_transaction_no': transaction}
        invalid = dict(body, request_no=body['request_no'] + '-invalid', related_transaction_no='not-owned')
        self.assertEqual(self.client.post('/finance/support/tickets', json=invalid).status_code, 404)
        first = self.client.post('/finance/support/tickets', json=body)
        self.assertEqual(first.status_code, 200, first.text)
        ticket_no = first.json()['data']['ticket_no']
        # 重复请求应从数据库中的幂等记录读取原结果。
        from app import finance_router
        finance_router._ticket_requests.clear()
        replay = self.client.post('/finance/support/tickets', json=body)
        self.assertEqual(replay.json()['data']['ticket_no'], ticket_no)
        changed = dict(body, ticket_content='相同请求号的不同内容')
        self.assertEqual(self.client.post('/finance/support/tickets', json=changed).status_code, 409)
        workflows = rows('''SELECT w.id FROM workflow_instance w JOIN support_ticket t
            ON w.related_id=t.id AND w.related_type='support_ticket'
            JOIN workflow_task task ON task.instance_id=w.id
            WHERE t.ticket_no=:number''', number=ticket_no)
        self.assertEqual(len(workflows), 1)
        other_customer = rows('SELECT customer_no FROM customer WHERE customer_no<>:number LIMIT 1',
                              number=self.customer)[0]['customer_no']
        self.assertEqual(self.client.get(
            f'/finance/customers/{other_customer}/support/tickets/{ticket_no}').status_code, 404)
        detail = self.client.get(f'/finance/customers/{self.customer}/support/tickets/{ticket_no}')
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['data']['ticket_status'], 'submitted')
        self.assertEqual(detail.json()['data']['transaction_no'], transaction)
        self.assertEqual(detail.json()['data']['process_status'], '待初审')
        saved_request = rows('''SELECT response_json FROM finassist_request_idempotency
            WHERE scope='support_ticket' AND request_no=:request_no''', request_no=body['request_no'])
        self.assertEqual(len(saved_request), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
