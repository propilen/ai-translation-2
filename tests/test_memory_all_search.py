from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.memory_api import router
from backend.translation_memory import search_memory
from test_memory_text_search import TextSearchTests


class AllSearchTests(TextSearchTests):
    def test_union_order_deduplication_and_limit(self):
        rows = search_memory(self.path, 'red pump', threshold=0, mode='all')
        self.assertEqual(rows[0]['source'], 'The red pump is ready.')
        self.assertEqual(rows[1]['source'], 'The pump is red.')
        self.assertEqual(rows[0]['matched_modes'], ['phrase', 'words', 'fuzzy'])
        self.assertEqual(rows[1]['matched_modes'], ['words', 'fuzzy'])
        self.assertEqual(len(rows), len({row['id'] for row in rows}))
        limited = search_memory(self.path, 'red pump', threshold=0, limit=1, mode='all')
        self.assertEqual(limited, rows[:1])
        strict = search_memory(self.path, 'red pump', threshold=100, mode='all')
        self.assertEqual(len(strict), 2)
        self.assertTrue(all('fuzzy' not in row['matched_modes'] for row in strict))

    def test_fuzzy_only_and_exact_first(self):
        fuzzy = search_memory(self.path, 'The red pumo is ready.', threshold=80, mode='all')
        self.assertEqual(fuzzy[0]['source'], 'The red pump is ready.')
        self.assertEqual(fuzzy[0]['matched_modes'], ['fuzzy'])
        exact = search_memory(self.path, 'The pump is red.', threshold=0, mode='all')
        self.assertTrue(exact[0]['exact'])
        self.assertEqual(exact[0]['score'], 100)
        self.assertEqual(search_memory(self.path, 'no such phrase', threshold=100, mode='all'), [])

    def test_all_mode_api_and_punctuation(self):
        app = FastAPI()
        app.include_router(router)
        with patch('backend.memory_api.memory_path', return_value=self.path):
            client = TestClient(app)
            response = client.get('/api/memories/test/search', params={'q': 'red pump', 'mode': 'all', 'threshold': 100})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['mode'], 'all')
            self.assertEqual(len(response.json()['results']), 2)
        punctuation = search_memory(self.path, '%', threshold=100, mode='all')
        self.assertEqual(len(punctuation), 1)
        self.assertEqual(punctuation[0]['matched_modes'], ['phrase'])
