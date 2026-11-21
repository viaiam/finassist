import asyncio
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from finassist.api.app import app
from finassist.api.dependencies import get_repository
from finassist.domain.state import DialogueState, TaskInstance
from finassist.domain.message import BotMessage, UserMessage, MessageType
from finassist.domain.state import Turn


class FakeRepository:
    def __init__(self):
        self.state = DialogueState(sender_id='experience-user')

    async def load_state(self, sender_id):
        return self.state

    async def save_state(self, state):
        self.state = state


class ChatExperienceTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        app.dependency_overrides[get_repository] = lambda: self.repository
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_status_exposes_active_and_paused_tasks(self):
        self.repository.state.tasks.active = TaskInstance('complaint_ticket', 'ask_ticket_type', task_id='active-1')
        self.repository.state.tasks.paused.append(TaskInstance('transaction_query', 'ask_transaction_date', task_id='paused-1'))
        response = self.client.get('/api/chat/status', params={'sender_id': 'experience-user'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['active_task']['flow_id'], 'complaint_ticket')
        self.assertEqual(response.json()['paused_tasks'][0]['task_id'], 'paused-1')

    def test_new_session_closes_current_and_clears_tasks(self):
        self.repository.state.shared.create_session()
        self.repository.state.tasks.active = TaskInstance('complaint_ticket', 'ask_ticket_type')
        response = self.client.post('/api/chat/sessions', json={'sender_id': 'experience-user'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.repository.state.tasks.active)
        self.assertEqual(len(self.repository.state.shared.sessions), 2)
        self.assertIsNotNone(self.repository.state.shared.sessions[0].closed_at)

    def test_status_reports_current_session(self):
        self.repository.state.shared.create_session()
        response = self.client.get('/api/chat/status', params={'sender_id': 'experience-user'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['session']['session_id'],
                         self.repository.state.shared.sessions[-1].session_id)

    def test_history_can_be_limited_to_current_session(self):
        self.repository.state.shared.create_session()
        old_session = self.repository.state.shared.sessions[-1]
        old_session.turns.append(Turn('old-turn', UserMessage(
            'experience-user', 'old-message', MessageType.TEXT, text='旧会话'),
            [BotMessage(text='旧回复')]))
        self.repository.state.shared.create_session()
        current_session = self.repository.state.shared.sessions[-1]
        current_session.turns.append(Turn('new-turn', UserMessage(
            'experience-user', 'new-message', MessageType.TEXT, text='新会话'),
            [BotMessage(text='新回复')]))
        response = self.client.get('/api/chat/history', params={
            'sender_id': 'experience-user', 'session_id': current_session.session_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([message['text'] for message in response.json()['messages']], ['新会话', '新回复'])

    def test_session_list_includes_preview_and_message_count(self):
        self.repository.state.shared.create_session()
        old_session = self.repository.state.shared.sessions[-1]
        old_session.turns.append(Turn('old-turn', UserMessage(
            'experience-user', 'old-message', MessageType.TEXT, text='查询账户余额'),
            [BotMessage(text='账户余额如下')]))
        self.repository.state.shared.create_session()
        current_session = self.repository.state.shared.sessions[-1]

        response = self.client.get('/api/chat/sessions', params={'sender_id': 'experience-user'})

        self.assertEqual(response.status_code, 200)
        sessions = response.json()['sessions']
        self.assertEqual([item['session_id'] for item in sessions], [
            current_session.session_id, old_session.session_id])
        self.assertEqual(sessions[1]['message_count'], 2)
        self.assertEqual(sessions[1]['preview'], '查询账户余额')
        self.assertFalse(sessions[0]['has_messages'])
