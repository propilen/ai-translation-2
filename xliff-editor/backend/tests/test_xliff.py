import unittest
from app import xliff
SAMPLE=b'''<?xml version="1.0"?><xliff version="1.2"><file original="x"><body><trans-unit id="a"><source>Hello <pc id="1">world</pc></source><target state="translated">Privet <pc id="1">mir</pc></target></trans-unit></body></file></xliff>'''
class XliffTests(unittest.TestCase):
 def test_parse_preserves_inline_fragment(self):
  _,_,_,segments=xliff.parse(SAMPLE);self.assertEqual(segments[0].source,'Hello world');self.assertIn('<pc id="1">mir</pc>',segments[0].target)
 def test_serializer_changes_target_without_losing_source(self):
  root,_,_,segments=xliff.parse(SAMPLE);xliff.set_target(root,segments[0].path,'Hello <pc id="1">planet</pc>','reviewed');result=__import__('xml.etree.ElementTree',fromlist=['']).tostring(root,encoding='unicode');self.assertIn('<source>Hello <pc id="1">world</pc></source>',result);self.assertIn('planet',result)
if __name__=='__main__':unittest.main()
