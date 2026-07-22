import unittest

from person_names import extract_person_names, rank_person_mentions
from storage import TitleCountRecord


class PersonNameExtractionTests(unittest.TestCase):
    def test_extracts_people_and_rejects_teams_and_labels(self) -> None:
        names = extract_person_names(
            "半场：三镇2-0新鹏城，熊继政破门，汪晋贤建功，加布里埃尔染红"
        )

        self.assertTrue({"熊继政", "汪晋贤", "加布里埃尔"}.issubset(names))
        self.assertNotIn("半场", names)
        self.assertNotIn("新鹏城", names)

    def test_extracts_translated_names_and_aliases(self) -> None:
        names = extract_person_names(
            "詹姆斯与马刺对话，丈夫保罗-乔治也入镜；莫德里奇倾向留队"
        )

        self.assertIn("詹姆斯", names)
        self.assertIn("保罗-乔治", names)
        self.assertIn("莫德里奇", names)
        self.assertNotIn("马刺", names)

    def test_ranking_counts_each_person_once_per_headline_capture(self) -> None:
        records = [
            TitleCountRecord(
                platform="hupu_nba",
                title="詹姆斯和勒布朗再次成为焦点",
                url="https://example.com/1",
                count=5,
                last_seen="2026-07-22T10:00:00+08:00",
            ),
            TitleCountRecord(
                platform="dongqiudi",
                title="勒布朗·詹姆斯回应传闻",
                url="https://example.com/2",
                count=3,
                last_seen="2026-07-22T11:00:00+08:00",
            ),
            TitleCountRecord(
                platform="dongqiudi",
                title="梅西获奖",
                url="https://example.com/3",
                count=2,
                last_seen="2026-07-22T12:00:00+08:00",
            ),
        ]

        results, total = rank_person_mentions(records)

        self.assertEqual(total, 2)
        self.assertEqual(results[0].name, "詹姆斯")
        self.assertEqual(results[0].count, 8)
        self.assertEqual(results[0].headline_count, 2)
        self.assertEqual(results[0].latest_url, "https://example.com/2")

        filtered, filtered_total = rank_person_mentions(records, query="勒布朗")
        self.assertEqual(filtered_total, 1)
        self.assertEqual(filtered[0].name, "詹姆斯")


if __name__ == "__main__":
    unittest.main()
