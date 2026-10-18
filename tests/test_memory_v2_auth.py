"""Integration checks for the 2.0 authentication middleware; no real user DB writes."""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.translation_memory import convert_tmx


class MemoryAuthorizationTests(unittest.TestCase):
    def test_requires_login(self):
        with patch('backend.app.read_session', return_value=None):
            client = TestClient(app)
            response = client.get('/memories.html', follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], '/login')
            for path in ['/api/memories', '/api/memories/invalid/search?q=text', '/api/memories/invalid/download', '/api/memories/invalid/download-tmx']:
                self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.post('/api/memories').status_code, 401)

    def test_regular_user_can_use_memory(self):
        user = dict(id=12, username='test', is_admin=False, can_access_settings=False, can_manage_filters=False)
        with tempfile.TemporaryDirectory() as directory, \
             patch('backend.app.read_session', return_value=user), \
             patch('backend.app.get_user', return_value=user), \
             patch('backend.memory_api.memory_directory', return_value=Path(directory)):
            client = TestClient(app)
            for path in ['/memories.html', '/memories.js', '/memories.css', '/app-navigation.js']:
                self.assertEqual(client.get(path).status_code, 200)
            self.assertIn('/app-navigation.js', client.get('/memories.html').text)
            self.assertIn('/memories.html', client.get('/app-navigation.js').text)
            self.assertEqual(client.get('/api/memories').json(), [])
            tmx = b'<tmx><body><tu><tuv xml:lang="en"><seg>Test</seg></tuv><tuv xml:lang="ru"><seg>Target</seg></tuv></tu></body></tmx>'
            response = client.post('/api/memories', files={'document': ('test.tmx', tmx)}, data={'source_language': 'en', 'target_language': 'ru'})
            self.assertEqual(response.status_code, 201, response.text)
            memory_id = response.json()['id']
            self.assertEqual(client.get(f'/api/memories/{memory_id}/search?q=Test').json()['results'][0]['score'], 100)
            self.assertEqual(client.get(f'/api/memories/{memory_id}/download').content[:16], b'SQLite format 3\x00')
            self.assertEqual(client.get('/settings.html').status_code, 403)
            self.assertEqual(client.get('/admin').status_code, 403)


if __name__ == '__main__':
    unittest.main()
