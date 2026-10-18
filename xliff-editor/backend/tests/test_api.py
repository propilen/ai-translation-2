import unittest, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app import db
SAMPLE=b'<xliff version="1.2"><file><body><trans-unit id="x"><source>One</source><target>One target</target></trans-unit></body></file></xliff>'
class ApiTests(unittest.TestCase):
 def setUp(self): self.temp=tempfile.TemporaryDirectory();self.old=db.database_path;db.database_path=lambda:Path(self.temp.name)/'test.db';self.client=TestClient(app)
 def tearDown(self): db.database_path=self.old;self.temp.cleanup()
 def test_upload_patch_and_export(self):
  r=self.client.post('/api/documents',files={'file':('a.xliff',SAMPLE,'application/xml')});self.assertEqual(r.status_code,201);doc=self.client.get('/api/documents/'+r.json()['id']).json();seg=doc['segments'][0];self.assertEqual(self.client.patch(f'/api/documents/{doc["id"]}/segments/{seg["id"]}',json={'target_xml':'Updated'}).status_code,200);self.assertIn(b'Updated',self.client.get('/api/documents/'+doc['id']+'/export').content)
if __name__=='__main__':unittest.main()
