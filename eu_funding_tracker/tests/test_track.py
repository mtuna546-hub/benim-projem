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
        (title, md, html_body), (_, summary, _), new_count = track.run(self.hits(), state, now=now)

        self.assertEqual(new_count, 1)  # the LIFE nature call does not match the profile
        self.assertIn("HORIZON-CL4-2027-DIGITAL-01-01", state["seen"])
        self.assertNotIn("LIFE-2027-NAT-01", state["seen"])
        self.assertIn("Test Akademisyen", md)
        self.assertNotIn("Başka Akademisyen", md)
        self.assertIn("İTO", md)
        self.assertIn("Teknopark İstanbul", md)
        self.assertIn("BTM", md)
        self.assertNotIn("BİM", md)
        self.assertIn("Türkiye ilişkili", md)
        self.assertIn("2026-10-15", md)  # within 30-day deadline window
        self.assertIn("<h1", html_body)
        self.assertIn("En uygun açık çağrılar", summary)

        # second run: nothing new
        _, (_, md2, _), new_count2 = track.run(self.hits(), state, now=now)
        self.assertEqual(new_count2, 0)
        self.assertIn("eşleşen yeni bir çağrı bulunamadı", md2)

    def test_generic_body_words_alone_do_not_match(self):
        hit = {"metadata": {
            "identifier": ["HORIZON-X-01"],
            "title": ["Advanced materials for batteries"],
            "descriptionByte": ["SMEs, startups, supply chain, cloud, software, trade, export, fintech."],
        }}
        state = {"seen": {}, "last_run": None}
        _, _, new_count = track.run([hit], state)
        self.assertEqual(new_count, 0)  # no focus keyword in the title

    def test_programme_label_falls_back_to_identifier_prefix(self):
        self.assertEqual(track.programme_label("43108390", "X"), "Horizon Europe")
        self.assertEqual(track.programme_label("44181033", "EDF-2026-RA-01"), "European Defence Fund")
        self.assertEqual(track.programme_label("999", "UNKNOWN-1"), "999")


    def test_engineering_profile_weights_programmes(self):
        eng = track.load_profile(track.HERE / "profile_muhendislik.json")
        base = track.load_profile()
        self.assertEqual(eng["ecosystem"], base["ecosystem"])  # inherited from profile.json
        hits = [
            {"metadata": {"identifier": ["HORIZON-JU-CHIPS-2026-RIA-01"],
                          "title": ["Power electronics and sensors for next-generation chips"]}},
            {"metadata": {"identifier": ["HORIZON-CL2-2026-HERITAGE-01"],
                          "title": ["AI tools for cultural heritage"]}},
        ]
        state = {"seen": {}, "last_run": None}
        (_, md, _), _, new_count = track.run(hits, state, profile=eng)
        self.assertEqual(new_count, 1)
        self.assertIn("HORIZON-JU-CHIPS-2026-RIA-01", md)
        self.assertIn("program ağırlığı +4", md)
        self.assertNotIn("cultural heritage", md)  # Cluster 2 penalty drops it

        # The general profile still keeps the cultural-heritage call.
        (_, md_general, _), _, _ = track.run(hits, {"seen": {}, "last_run": None}, profile=base)
        self.assertIn("AI tools for cultural heritage", md_general)

    def test_issue_body_nests_general_report(self):
        body = track.build_issue_body([("Mühendislik", "# Müh raporu"), ("Genel", "# Genel rapor")])
        self.assertTrue(body.startswith("# Müh raporu"))
        self.assertIn("<details>", body)
        self.assertIn("# Genel rapor", body)

        big = track.build_issue_body([("Müh", "x" * 50000), ("Genel", "y" * 20000)])
        self.assertLess(len(big), track.ISSUE_BODY_LIMIT)
        self.assertIn("sığmadı", big)


    def test_stale_and_multi_cutoff_deadlines(self):
        now = datetime(2026, 9, 29, tzinfo=timezone.utc)
        hits = [
            {"metadata": {"identifier": ["HORIZON-CL4-2024-DIGITAL-01"],
                          "title": ["AI-powered robots for trade and logistics"],
                          "deadlineDate": ["2024-03-19T17:00:00.000+0000"]}},
            {"metadata": {"identifier": ["HORIZON-CL4-2026-DIGITAL-02"],
                          "title": ["AI-powered robots for supply chain logistics"],
                          "deadlineDate": ["2026-02-01T17:00:00.000+0000", "2027-02-01T17:00:00.000+0000"]}},
        ]
        (_, md, _), _, new_count = track.run(hits, {"seen": {}, "last_run": None}, now=now)
        self.assertEqual(new_count, 1)
        self.assertNotIn("HORIZON-CL4-2024-DIGITAL-01", md)
        self.assertIn("**Son başvuru:** 2027-02-01", md)
        self.assertIn("1 çağrı elendi", md)


    def test_edf_calls_are_excluded_from_both_profiles(self):
        hits = [{"metadata": {"identifier": ["EDF-2026-RA-SENS-MSDT"],
                              "title": ["Multidomain sensors and AI for logistics and supply chain"]}}]
        for name in ("profile.json", "profile_muhendislik.json"):
            profile = track.load_profile(track.HERE / name)
            _, _, new_count = track.run(hits, {"seen": {}, "last_run": None}, profile=profile)
            self.assertEqual(new_count, 0, name)

    def test_parse_topic_details(self):
        data = {"TopicDetails": {
            "actions": [{"types": [{"typeOfAction": "HORIZON-RIA HORIZON Research and Innovation Actions",
                                    "typeOfMGA": [{"abbreviation": "HORIZON-AG-LS"}]}]}],
            "budgetOverviewJSONItem": {"budgetTopicActionMap": {"1": [
                {"action": "HORIZON-OTHER-01 - HORIZON-IA", "minContribution": 1, "maxContribution": 1},
                {"action": "HORIZON-CL4-2027-01-X-01 - HORIZON-RIA HORIZON Research and Innovation Actions",
                 "budgetYearMap": {"2027": "30000000"}, "minContribution": 4000000,
                 "maxContribution": 6000000, "expectedGrants": 5}]}}}}
        d = track.parse_topic_details("HORIZON-CL4-2027-01-X-01", data)
        self.assertEqual(d["mga"], "HORIZON-AG-LS")
        self.assertEqual(track.short_action(d["action_full"]), "RIA")
        self.assertEqual((d["min"], d["max"], d["grants"], d["budget"]), (4000000, 6000000, 5, 30000000))
        self.assertEqual(track.short_action(None, "Robots for industry (IA)"), "IA")
        self.assertEqual(track.short_action("HORIZON-JU-RIA HORIZON JU Research"), "JU-RIA")

    def test_lump_sum_ria_csa_ranked_first_then_ia(self):
        hits = [
            {"metadata": {"identifier": [f"HORIZON-CL4-2027-0{i}"],
                          "title": [f"Artificial intelligence for supply chain logistics {i}"]}}
            for i in range(1, 5)
        ]
        details = {
            "HORIZON-CL4-2027-01": {"action_full": "HORIZON-IA x", "mga": "HORIZON-AG"},
            "HORIZON-CL4-2027-02": {"action_full": "HORIZON-IA x", "mga": "HORIZON-AG-LS"},
            "HORIZON-CL4-2027-03": {"action_full": "HORIZON-CSA x", "mga": "HORIZON-AG-LS"},
            "HORIZON-CL4-2027-04": {"action_full": "HORIZON-RIA x", "mga": "HORIZON-AG-LS", "min": 3000000,
                                    "max": 5000000, "grants": 4},
        }
        cache = {}
        (_, md, _), (_, summary, _), _ = track.run(
            hits, {"seen": {}, "last_run": None}, details_fetcher=lambda i: details[i], details_cache=cache)
        pos = {i: md.index(f"HORIZON-CL4-2027-0{i}`") for i in (1, 2, 3, 4)}
        # RIA/CSA lump sum, then IA lump sum, then budget-based
        self.assertLess(max(pos[3], pos[4]), pos[2])
        self.assertLess(pos[2], pos[1])
        self.assertIn("Lump sum öncelikli çağrılar", summary)
        self.assertIn("RIA·LS", summary)
        self.assertIn("proje başı 3–5 M€", md)
        self.assertIn("Tüm eşleşen çağrılar (4)", md)
        self.assertIn("HORIZON-CL4-2027-04", cache)

        profile = dict(track.load_profile(), only_lump_sum=True)
        (_, md_ls, _), _, _ = track.run(hits, {"seen": {}, "last_run": None}, profile=profile,
                                        details_fetcher=lambda i: details[i])
        self.assertNotIn("HORIZON-CL4-2027-01`", md_ls)

    def test_cancelled_and_cascade_calls(self):
        hits = [
            {"metadata": {"identifier": ["HORIZON-EIE-2027-01-CONNECT-01-CANCELLED"],
                          "title": ["Startup Europe for entrepreneurship"]}},
            {"metadata": {"identifier": ["HORIZON-CL4-2023-DIGITAL-EMERGING-01-02"],
                          "title": ["Artificial intelligence and robotics for logistics"],
                          "url": ["https://ec.europa.eu/.../competitive-calls-cs/45634882"]}},
        ]
        (_, md, _), _, new_count = track.run(hits, {"seen": {}, "last_run": None},
                                             details_fetcher=lambda i: self.fail("no fetch for cascade"))
        self.assertEqual(new_count, 1)
        self.assertNotIn("CANCELLED", md)
        self.assertIn("Kaskad fonlama (FSTP)", md)


if __name__ == "__main__":
    unittest.main()
