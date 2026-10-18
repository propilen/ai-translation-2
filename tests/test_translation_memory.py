import io
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.memory_api import router
from backend.translation_memory import convert_tmx, search_memory


TMX = '''<?xml version="1.0"?><tmx version="1.4"><header srclang="en"/><body>
<tu tuid="one"><tuv xml:lang="en"><seg>Hello <bpt i="1">&lt;b&gt;</bpt>world<ept i="1">&lt;/b&gt;</ept>!</seg></tuv><tuv xml:lang="ru"><seg>Привет, мир!</seg></tuv></tu>
<tu><tuv xml:lang="en"><seg>Hello world!</seg></tuv><tuv xml:lang="ru"><seg>Привет, мир!</seg></tuv></tu>
<tu><tuv xml:lang="en"><seg>Hello worlds!</seg></tuv><tuv xml:lang="ru"><seg>Привет, миры!</seg></tuv></tu>
<tu><tuv xml:lang="de"><seg>Hallo</seg></tuv></tu>
</body></tmx>'''


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.path = self.directory / 'memory.sqlite'

    def tearDown(self):
        self.tmp.cleanup()

    def convert(self, content=TMX, **kwargs):
        return convert_tmx(io.BytesIO(content.encode()), self.path, 'Test', 'en', 'ru', **kwargs)

    def test_import_and_rank(self):
        meta = self.convert()
        self.assertEqual((meta['count'], meta['duplicates'], meta['skipped']), (2, 1, 1))
        matches = search_memory(self.path, ' HELLO   WORLD! ', 70)
        self.assertEqual(matches[0]['score'], 100)
        self.assertEqual(matches[0]['source'], 'Hello world!')
        self.assertLess(matches[1]['score'], 100)
        self.assertGreater(matches[1]['score'], 70)
        self.assertEqual(len(search_memory(self.path, 'Hello world!', 100)), 1)
        self.assertEqual(search_memory(self.path, 'Completely unrelated text', 90), [])
        self.assertEqual(len(search_memory(self.path, 'Hello world!', 0, 1)), 1)

    def test_invalid_import_is_atomic(self):
        for content in [TMX[:-10], '<html/>', TMX.replace('xml:lang="en"', 'xml:lang="en-US"'),
                        '<!DOCTYPE tmx [<!ENTITY x "boom">]><tmx>&x;</tmx>']:
            with self.assertRaises(Exception):
                self.convert(content)
            self.assertFalse(self.path.exists())

    def test_never_overwrite(self):
        self.convert()
        with self.assertRaises(FileExistsError):
            self.convert()
        self.assertEqual(len(search_memory(self.path, 'Hello world!')), 2)

    def test_search_indexes_are_rebuilt_for_existing_memory(self):
        self.convert()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                DROP TRIGGER IF EXISTS segments_search_ai;
                DROP TRIGGER IF EXISTS segments_search_ad;
                DROP TRIGGER IF EXISTS segments_search_au;
                DROP TABLE IF EXISTS segments_fts;
                DROP TABLE IF EXISTS segments_trigram;
                PRAGMA user_version=0;
            ''')
        self.assertEqual(search_memory(self.path, 'Hello world!', 100)[0]['score'], 100)
        with closing(sqlite3.connect(self.path)) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('segments_fts','segments_trigram')"
            )}
        self.assertEqual(tables, {'segments_fts', 'segments_trigram'})

    def test_api(self):
        app = FastAPI()
        app.include_router(router)
        with patch('backend.memory_api.memory_directory', return_value=self.directory), TestClient(app) as client:
            self.assertEqual(client.get('/api/memories').json(), [])
            response = client.post('/api/memories', files={'document': ('test.tmx', TMX.encode(), 'application/xml')},
                                   data={'source_language': 'en', 'target_language': 'ru'})
            self.assertEqual(response.status_code, 201, response.text)
            memory_id = response.json()['id']
            self.assertEqual(len(client.get('/api/memories').json()), 1)
            segment = client.post(f'/api/memories/{memory_id}/segments', json={'source': 'New segment', 'target': 'Новый сегмент', 'tuid': 'external-1', 'author': 'CAT Editor'})
            self.assertEqual(segment.status_code, 201, segment.text)
            self.assertTrue(segment.json()['added'])
            self.assertEqual(segment.json()['author'], 'CAT Editor')
            self.assertTrue(segment.json()['created_at'])
            indexed = client.get(f'/api/memories/{memory_id}/search', params={'q': 'New segment', 'mode': 'words'})
            self.assertEqual([row['id'] for row in indexed.json()['results']], [segment.json()['id']])
            exported = client.get(f'/api/memories/{memory_id}/download-tmx')
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertIn('attachment; filename=', exported.headers['content-disposition'])
            exported_root = ElementTree.fromstring(exported.content)
            exported_unit = next(unit for unit in exported_root.iter('tu') if unit.get('tuid') == 'external-1')
            self.assertEqual(exported_unit.get('creationid'), 'CAT Editor')
            self.assertRegex(exported_unit.get('creationdate'), r'^\d{8}T\d{6}Z$')
            exported_variants = {variant.get('{http://www.w3.org/XML/1998/namespace}lang'): variant.findtext('seg') for variant in exported_unit.findall('tuv')}
            self.assertEqual(exported_variants, {'en': 'New segment', 'ru': 'Новый сегмент'})
            duplicate = client.post(f'/api/memories/{memory_id}/segments', json={'source': 'New segment', 'target': 'Новый сегмент'})
            self.assertEqual(duplicate.status_code, 201, duplicate.text)
            self.assertTrue(duplicate.json()['duplicate'])
            self.assertEqual(client.delete(f"/api/memories/{memory_id}/segments/{segment.json()['id']}").status_code, 204)
            removed = client.get(f'/api/memories/{memory_id}/search', params={'q': 'New segment', 'mode': 'words'})
            self.assertEqual(removed.json()['results'], [])
            self.assertEqual(client.delete(f"/api/memories/{memory_id}/segments/{segment.json()['id']}").status_code, 404)
            self.assertEqual(client.post(f'/api/memories/{memory_id}/segments', json={'source': ' ', 'target': 'Текст'}).status_code, 422)
            response = client.get(f'/api/memories/{memory_id}/search', params={'q': 'Hello world!'})
            self.assertEqual(len(response.json()['results']), 2)
            self.assertEqual(client.get(f'/api/memories/{memory_id}/download').content[:16], b'SQLite format 3\x00')
            self.assertEqual(client.get('/api/memories/invalid/search', params={'q': 'test'}).status_code, 404)
            self.assertEqual(client.get(f'/api/memories/{memory_id}/search', params={'q': '   '}).status_code, 422)
            self.assertEqual(client.get(f'/api/memories/{memory_id}/search', params={'q': 'test', 'threshold': 101}).status_code, 422)
            response = client.post('/api/memories', files={'document': ('broken.tmx', b'<tmx>')},
                                   data={'source_language': 'en', 'target_language': 'ru'})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(len(client.get('/api/memories').json()), 1)


if __name__ == '__main__':
    unittest.main()
