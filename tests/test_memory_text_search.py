import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.memory_api import router
from backend.translation_memory import convert_tmx, search_memory


class TextSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'memory.sqlite'
        texts = ['The red pump is ready.', 'The pump is red.', 'A red pumping unit.',
                 'Большой красный насос работает.', 'Красный, насос.', 'Красный насосик.',
                 'Discount 10%_ now.', 'Discount 1000 now.', 'Use C++ here.']
        xml = '<tmx><body>' + ''.join(f'<tu><tuv xml:lang="en"><seg>{escape(text)}</seg></tuv><tuv xml:lang="ru"><seg>translation</seg></tuv></tu>' for text in texts) + '</body></tmx>'
        convert_tmx(io.BytesIO(xml.encode()), self.path, 'Test', 'en', 'ru')

    def tearDown(self):
        self.temp.cleanup()

    def sources(self, query, mode, **kwargs):
        return [row['source'] for row in search_memory(self.path, query, mode=mode, **kwargs)]

    def test_words_are_whole_and_unordered(self):
        self.assertEqual(self.sources('PUMP red', 'words'), ['The red pump is ready.', 'The pump is red.'])
        self.assertEqual(self.sources('насос КРАСНЫЙ', 'words'), ['Большой красный насос работает.', 'Красный, насос.'])
        self.assertEqual(self.sources('red missing', 'words'), [])
        self.assertEqual(len(self.sources('red', 'words', limit=1)), 1)
        with self.assertRaises(ValueError):
            self.sources('!!!', 'words')

    def test_phrase_order_boundaries_and_normalization(self):
        self.assertEqual(self.sources(' RED\n pump ', 'phrase'), ['The red pump is ready.'])
        self.assertEqual(self.sources('красный насос', 'phrase'), ['Большой красный насос работает.'])
        self.assertEqual(self.sources('10%_', 'phrase'), ['Discount 10%_ now.'])
        self.assertEqual(self.sources('C++', 'phrase'), ['Use C++ here.'])
        self.assertEqual(self.sources('pump red', 'phrase'), [])

    def test_api_mode_validation_and_compatibility(self):
        app = FastAPI()
        app.include_router(router)
        with patch('backend.memory_api.memory_path', return_value=self.path):
            client = TestClient(app)
            url = '/api/memories/test/search'
            response = client.get(url, params={'q': 'red pump', 'mode': 'phrase', 'threshold': 100})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['mode'], 'phrase')
            self.assertEqual(len(response.json()['results']), 1)
            self.assertIsNone(response.json()['results'][0]['score'])
            self.assertEqual(len(client.get(url, params={'q': 'red pump', 'mode': 'words'}).json()['results']), 2)
            self.assertEqual(client.get(url, params={'q': 'red', 'mode': 'invalid'}).status_code, 422)
            self.assertEqual(client.get(url, params={'q': '!!!', 'mode': 'words'}).status_code, 422)
            self.assertEqual(client.get(url, params={'q': 'The red pump is ready.'}).json()['results'][0]['score'], 100)


if __name__ == '__main__':
    unittest.main()
