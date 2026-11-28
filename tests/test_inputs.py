from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from steel_inputs import load_inputs
from steel_inputs.import_workbooks import normalize_plan_row, timestamp


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = load_inputs()

    def test_account_for_every_plan_row(self):
        accepted = {job.source_row for job in self.inputs.jobs}
        excluded = {row["source_row"] for row in self.inputs.rejected_plan_rows}
        self.assertEqual(len(accepted), 1266)
        self.assertEqual(len(excluded), 55)
        self.assertFalse(accepted & excluded)
        self.assertEqual(accepted | excluded, set(range(2, 1323)))
        self.assertTrue(all(job.heat_id != "-2" for job in self.inputs.jobs))
        self.assertEqual(len({job.job_id for job in self.inputs.jobs}), len(accepted))

    def test_all_four_routes_are_ordered_by_route_code(self):
        expected = {"L0": ("LF",), "R0": ("RH",), "L0R0": ("LF", "RH"), "R0L0": ("RH", "LF")}
        self.assertEqual({job.route_code for job in self.inputs.jobs}, set(expected))
        for job in self.inputs.jobs:
            self.assertEqual(tuple(stage.kind for stage in job.stages[1:-1]), expected[job.route_code])
            self.assertTrue(all(stage.candidates for stage in job.stages))

    def test_known_example_is_accessible(self):
        group = self.inputs.jobs_for_cast("CC3", "6C0776")
        example = next(job for job in group if job.heat_id == "26BD6651")
        self.assertEqual(example.source_row, 1306)
        self.assertEqual(example.transport_edges, ("BOF->LF", "LF->RH", "RH->CC"))
        self.assertEqual(group, tuple(sorted(group, key=lambda job: (job.cast_start, job.source_row))))
        self.assertTrue(all(stage.planned_seconds > 0 for stage in example.stages))
        self.assertNotIn("LF2", example.stages[1].candidates)

    def test_transport_and_unavailable_segment(self):
        self.assertEqual(self.inputs.transport_seconds("BOF->LF"), 346)
        self.assertEqual(self.inputs.transport_seconds("RH->CC", "p90"), 615)
        with self.assertRaises(KeyError):
            self.inputs.transport_seconds("EMPTY->REPAIR")
        with self.assertRaises(ValueError):
            self.inputs.transport_seconds("LF->RH", "max")
        self.assertIsNone(self.inputs.resources["dispatch_geometry"])
        self.assertTrue(any(row["metric"] == "铸机接受位重包放下重量" and row["unit"] == "吨"
                            for row in self.inputs.weight_stats))

    def test_detail_count_disagreement_is_kept(self):
        counts = {edge: sum(item["route"] == edge for item in self.inputs.transport_samples)
                  for edge in self.inputs.transport}
        for edge, item in self.inputs.transport.items():
            self.assertEqual(item["detail_sample_count"], counts[edge])
            self.assertEqual("summary_and_detail_count_differ" in item["issues"],
                             item["sample_count"] != counts[edge])
            self.assertTrue(Decimal(str(item["median"])) > 0)

    def test_history_duplicates_and_reversed_timestamps_are_preserved(self):
        self.assertEqual(len(self.inputs.history), 1350)
        self.assertEqual(len({row.heat_id for row in self.inputs.history}), 1278)
        with_id = {row.source_row for row in self.inputs.history}
        without_id = {row["source_row"] for row in self.inputs.rejected_history_rows}
        self.assertEqual(without_id, {208, 558, 573, 1193, 1322})
        self.assertFalse(with_id & without_id)
        self.assertEqual(with_id | without_id, set(range(2, 1357)))
        repeated = next(row for row in self.inputs.history if "repeated_historical_heat" in row.issues)
        self.assertGreater(len(self.inputs.history_for(repeated.heat_id)), 1)
        sample = next(row for row in self.inputs.history_for("26BD6651") if row.source_row == 21)
        self.assertEqual(sample.elapsed_seconds("tapping_end", "loaded_pickup"), 927)
        self.assertIsNone(sample.elapsed_seconds("rh_arrive", "rh_process_start"))
        self.assertIn("reversed_events:rh_arrive->rh_process_start", sample.issues)
        self.assertIsNone(sample.elapsed_seconds("not_recorded", "loaded_pickup"))

    def test_window_is_half_open(self):
        first, second = self.inputs.jobs[:2]
        self.assertIn(first, self.inputs.jobs_between(first.cast_start, second.cast_start))
        self.assertNotIn(second, self.inputs.jobs_between(first.cast_start, second.cast_start))
        with self.assertRaises(ValueError):
            self.inputs.jobs_between(first.cast_start, first.cast_start)

    def test_wrong_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema"):
                load_inputs(path)

    def test_placeholder_requires_no_route(self):
        job, issue = normalize_plan_row({"熔炼号": "-2", "配包flag": -2.0}, 9, None)
        self.assertIsNone(job)
        self.assertEqual(issue["reason"], "placeholder")

    def test_timestamp_conversion(self):
        self.assertIsNone(timestamp(""))
        self.assertEqual(timestamp(1.0, lambda _: datetime(2026, 10, 1, 9, 0, 0, 999999)),
                         "2026-10-01 09:00:01")


if __name__ == "__main__":
    unittest.main()
