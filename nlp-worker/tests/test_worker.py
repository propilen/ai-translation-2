"""Compare worker responses to the unchanged web-service NLP implementation."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import nlp_glossary as direct


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "nlp-worker" / "worker.py"
sys.path.insert(0, str(SCRIPT.parent))
from protocol import ProtocolError, WorkerProtocol  # noqa: E402


class WorkerProcess:
    def __init__(self, command):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)
        self.next_id = 0

    def send(self, action, **fields):
        self.next_id += 1
        request = {"id": self.next_id, "action": action, **fields}
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise AssertionError(f"Worker exited early: {self.process.poll()}; stderr: {self.process.stderr.read()}")
        response = json.loads(line)
        assert response["id"] == request["id"]
        return response

    def close(self):
        if self.process.poll() is None:
            self.send("shutdown")
        self.process.stdin.close()
        self.process.wait(timeout=10)
        assert self.process.returncode == 0, self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tsv = Path(self.temp.name) / "terms.tsv"
        self.tsv.write_text(
            "# UTF-8 glossary\n"
            "Fahrzeug\tавтомобиль\nFahrzeuge\tмашины\n"
            "neue Fahrzeuge\tновые автомобили\nMotor\tдвигатель\n"
            "vehicle\tтранспорт\nbeautiful cars\tкрасивые машины\n"
            "автомобиль\tcar\nкрасивый автомобиль\tbeautiful car\n"
            "и\tand\nC++\tси плюс плюс\n", encoding="utf-8-sig")
        self.workers = [WorkerProcess([sys.executable, str(SCRIPT)])]
        if os.environ.get("NLP_WORKER_EXE"):
            self.workers.append(WorkerProcess([os.environ["NLP_WORKER_EXE"]]))

    def tearDown(self):
        for worker in self.workers:
            worker.close()
        self.temp.cleanup()

    def test_lemmas_and_glossary_match_direct_calls(self):
        samples = {
            "ru": ["красивыми автомобилями", "И красивые автомобили, и моторы!", "", "Ёжик — ёлки"],
            "en": ["The vehicles are moving", "Beautiful cars!", "", "C++ — cafés"],
            "de": ["Die Fahrzeuge werden überprüft", "Neue Fahrzeuge, Motoren!", "", "Größe — Straße"],
        }
        texts = {
            "ru": ["Красивыми автомобилями", "И красивые автомобили, и красивые автомобили!", "", "И, и!"],
            "en": ["Beautiful cars, beautiful cars!", "The vehicle, the vehicle.", "", "C++!"],
            "de": ["Neue Fahrzeuge und Motoren!", "Die Fahrzeuge, die Fahrzeuge.", "", "C++!"],
        }
        for lang in ("ru", "en", "de"):
            direct.init_nlp(lang)
            expected_lemmas = [direct.lemmatize(text, lang) for text in samples[lang]]
            expected_terms = direct.load_glossary(self.tsv, lang)
            for worker in self.workers:
                self.assertEqual(worker.send("lemmatize_batch", lang=lang, texts=samples[lang])["lemmas"], expected_lemmas)
                response = worker.send("load_glossary", glossary_id=lang, lang=lang, path=str(self.tsv))
                self.assertEqual(response["count"], len(expected_terms))
                for threshold in (0, 0.85, 0.86, 1):
                    expected = [direct.find_glossary_terms(text, lang, expected_terms, threshold) or [] for text in texts[lang]]
                    actual = worker.send("find_terms_batch", glossary_id=lang, lang=lang, texts=texts[lang], threshold=threshold)
                    self.assertEqual(actual["terms"], expected)
                single = worker.send("find_terms", glossary_id=lang, lang=lang, text=texts[lang][0])
                self.assertEqual(single["terms"], direct.find_glossary_terms(texts[lang][0], lang, expected_terms) or [])

    def test_atomic_reload_errors_and_1000_requests(self):
        for worker in self.workers:
            self.assertEqual(worker.send("ping")["status"], "ready")
            self.assertTrue(worker.send("load_glossary", glossary_id="de", lang="de", path=str(self.tsv))["ok"])
            original = worker.send("find_terms", glossary_id="de", lang="de", text="Die Fahrzeuge")
            missing = worker.send("load_glossary", glossary_id="de", lang="de", path=str(self.tsv) + ".missing")
            self.assertEqual(missing["error"]["code"], "GLOSSARY_FILE_NOT_FOUND")
            self.assertEqual(worker.send("find_terms", glossary_id="de", lang="de", text="Die Fahrzeuge"),
                             {**original, "id": worker.next_id})
            self.assertEqual(worker.send("find_terms", glossary_id="de", lang="de", text="x", threshold=2)["error"]["code"], "INVALID_THRESHOLD")
            self.assertEqual(worker.send("find_terms", glossary_id="missing", lang="de", text="x")["error"]["code"], "GLOSSARY_NOT_FOUND")
            self.assertEqual(worker.send("whatever")["error"]["code"], "UNKNOWN_ACTION")
            self.assertEqual(worker.send("lemmatize", lang="fr", text="x")["error"]["code"], "UNSUPPORTED_LANGUAGE")
            self.assertEqual(worker.send("lemmatize_batch", lang="en", texts=["ok", 1])["error"]["code"], "INVALID_REQUEST")
            worker.process.stdin.write("{invalid json\n")
            worker.process.stdin.flush()
            self.assertEqual(json.loads(worker.process.stdout.readline())["error"]["code"], "INVALID_JSON")
            for _ in range(1000):
                self.assertTrue(worker.send("find_terms", glossary_id="de", lang="de", text="Motor")["ok"])
            self.assertIsNone(worker.process.poll())
            self.assertTrue(worker.send("unload_glossary", glossary_id="de")["unloaded"])
            self.assertEqual(worker.send("find_terms", glossary_id="de", lang="de", text="Motor")["error"]["code"], "GLOSSARY_NOT_FOUND")

    def test_model_failure_and_stdin_close(self):
        with patch.object(direct, "nlp_de", None), patch.object(direct, "init_nlp", side_effect=RuntimeError("missing model")):
            with self.assertRaises(ProtocolError) as error:
                WorkerProtocol().dispatch({"id": 1, "action": "lemmatize", "lang": "de", "text": "Hallo"})
            self.assertEqual(error.exception.code, "NLP_MODEL_ERROR")
        extra = WorkerProcess([sys.executable, str(SCRIPT)])
        self.assertTrue(extra.send("ping")["ok"])
        extra.process.stdin.close()
        self.assertEqual(extra.process.wait(timeout=10), 0)
        extra.process.stdout.close()
        extra.process.stderr.close()

    def test_known_lemmas(self):
        for worker in self.workers:
            self.assertEqual(worker.send("lemmatize", lang="ru", text="красивыми автомобилями")["lemmas"],
                             ["красивый", "автомобиль"])
            self.assertEqual(worker.send("lemmatize", lang="en", text="The vehicles")["lemmas"],
                             ["the", "vehicle"])
            self.assertEqual(worker.send("lemmatize", lang="de", text="Die Fahrzeuge")["lemmas"],
                             ["der", "fahrzeug"])

    def test_grammar_protocol_validation(self):
        protocol = WorkerProtocol()
        with self.assertRaises(ProtocolError) as error:
            protocol.dispatch({"id": 1, "action": "analyze", "lang": "en", "text": "Cars move."})
        self.assertEqual(error.exception.code, "UNSUPPORTED_GRAMMAR_LANGUAGE")

    def test_russian_grammar_and_offsets(self):
        try:
            response = self.workers[0].send("check_grammar", lang="ru", text="Эти автомобиль быстро едет.")
        except AssertionError:
            raise
        self.assertTrue(response["ok"])
        self.assertTrue(any(issue["rule_id"] == "RU_DET_NOUN_AGREEMENT" for issue in response["issues"]))
        emoji = "😀 Эти автомобиль"
        analysis = self.workers[0].send("analyze", lang="ru", text=emoji)
        token = next(item for item in analysis["sentences"][0]["tokens"] if item["text"] == "Эти")
        self.assertGreater(token["start_utf16"], token["start_cp"])

    def test_grammar_batch_preserves_order(self):
        response = self.workers[0].send("check_grammar_batch", lang="ru", texts=["Эти автомобили едут.", "Автомобили едет."])
        self.assertEqual(len(response["issues"]), 2)
        self.assertEqual(response["issues"][0], [])

    def test_grammar_regression_corpus_and_placeholders(self):
        bad = ["Она должен быть неподвижна.", "Машина приехал.", "Автомобили едет.", "Новая автомобили стоят возле дома."]
        good = ["Она должна быть неподвижна.", "Машина приехала.", "Автомобили едут.", "Автомобиль %1 был припаркован."]
        for worker in self.workers:
            for text in bad:
                self.assertTrue(worker.send("check_grammar", lang="ru", text=text)["issues"], text)
            for text in good:
                self.assertEqual(worker.send("check_grammar", lang="ru", text=text)["issues"], [], text)
if __name__ == "__main__":
    unittest.main()
