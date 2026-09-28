import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import track  # noqa: E402

FIXTURE = Path(__file__).parent / "sample_response.json"


class TrackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "academics.csv"
        csv_path.write_text(
            "name,department,email,focus_areas,keywords\n"
            "# comment line\n"
            "Test Akademisyen,Bilgisayar Müh.,t@x.edu.tr,digital_ai,supply chain resilience\n"
            "Başka Akademisyen,Hukuk,b@x.edu.tr,law_governance,\n",
            encoding="utf-8",
        )
        self._orig = track.ACADEMICS_PATH
        track.ACADEMICS_PATH = csv_path
        track.load_academics.__defaults__ = (csv_path,)

    def tearDown(self):
        track.ACADEMICS_PATH = self._orig
        track.load_academics.__defaults__ = (self._orig,)
        self.tmp.cleanup()

    def hits(self):
        return json.loads(FIXTURE.read_text(encoding="utf-8"))["results"]

    def test_matching_and_report(self):
        state = {"seen": {}, "last_run": None}
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        (title, md, html_body), new_count = track.run(self.hits(), state, now=now)

        self.assertEqual(new_count, 1)  # the LIFE nature call does not match the profile
        self.assertIn("HORIZON-CL4-2027-DIGITAL-01-01", state["seen"])
        self.assertNotIn("LIFE-2027-NAT-01", state["seen"])
        self.assertIn("Test Akademisyen", md)
        self.assertNotIn("Başka Akademisyen", md)
        self.assertIn("İTO", md)
        self.assertIn("Teknopark İstanbul", md)
        self.assertIn("Türkiye ilişkili", md)
        self.assertIn("2026-10-15", md)  # within 30-day deadline window
        self.assertIn("<h1", html_body)

        # second run: nothing new
        (_, md2, _), new_count2 = track.run(self.hits(), state, now=now)
        self.assertEqual(new_count2, 0)
        self.assertIn("eşleşen yeni bir çağrı bulunamadı", md2)


if __name__ == "__main__":
    unittest.main()
