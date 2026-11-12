"""Data-contract, feature, leakage, and small ML/SAT integration checks."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from models import mlsat


ROOT = Path(__file__).resolve().parents[1]
HAS_NUMPY = importlib.util.find_spec("numpy") is not None
HAS_SKLEARN = HAS_NUMPY and importlib.util.find_spec("sklearn") is not None
HAS_Z3 = importlib.util.find_spec("z3") is not None


def tiny_records():
    return [
        {"family": "fixture", "ordinal": i, "matching_sha256": f"{i:064x}",
         "old_bounded_unknown": int(i >= 8),
         "features": {"signal": -1.0 if i < 8 else 1.0, "count": float(i % 4)}}
        for i in range(16)
    ]


def write_training(path, rows):
    path.write_text(json.dumps({"format": "k22-training-records-v1",
                               "label_description": "Fixture bounded outcome, not torsion-freeness.",
                               "records": rows}), encoding="utf-8")


def rectangle_matching():
    matching = []
    for i in range(1, 23, 2):
        for j in range(1, 23, 2):
            matching.extend([[[i, j], [i + 1, j + 1]],
                             [[i, j + 1], [i + 1, j]]])
    return matching


class TrainingDataTests(unittest.TestCase):
    def test_public_table_and_manifest_agree(self):
        table_path = ROOT / "models/training_records.json"
        manifest = json.loads((ROOT / "models/training_manifest.json").read_text())
        rows, names = mlsat.read_records(table_path)
        self.assertEqual(names, manifest["feature_names"])
        self.assertEqual(len(names), 155)
        self.assertEqual(len(rows), manifest["record_count"])
        self.assertEqual(hashlib.sha256(table_path.read_bytes()).hexdigest(),
                         manifest["public_table_sha256"])
        self.assertEqual(len({r["matching_sha256"] for r in rows}), len(rows))
        for row in rows:
            self.assertEqual(set(row), {"family", "ordinal", "matching_sha256",
                                        "old_bounded_unknown", "features"})
            self.assertRegex(row["matching_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(set(row["features"]), set(names))
            self.assertTrue(all(math.isfinite(v) for v in row["features"].values()))

    def test_feature_vector_checks_names_types_and_finiteness(self):
        self.assertEqual(mlsat.feature_vector({"b": 3, "a": 2.5}, ["a", "b"]), [2.5, 3.0])
        for invalid in ({"a": 1}, {"a": 1, "b": 2, "c": 3},
                        {"a": True, "b": 2}, {"a": "1", "b": 2},
                        {"a": float("nan"), "b": 2}, {"a": float("inf"), "b": 2}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mlsat.feature_vector(invalid, ["a", "b"])

    def test_read_records_rejects_invalid_label_and_changed_feature_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "training.json"
            for label in (True, "1", 2, -1, 0.0):
                rows = tiny_records()
                rows[0][mlsat.LABEL] = label
                write_training(path, rows)
                with self.subTest(label=label), self.assertRaises(ValueError):
                    mlsat.read_records(path)
            rows = tiny_records()
            rows[-1]["features"]["unexpected"] = 0
            write_training(path, rows)
            with self.assertRaises(ValueError):
                mlsat.read_records(path)

    def test_read_records_requires_supported_format_and_both_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "training.json"
            path.write_text(json.dumps({"format": "not-supported", "records": tiny_records()}))
            with self.assertRaises(ValueError):
                mlsat.read_records(path)
            rows = tiny_records()
            for row in rows:
                row[mlsat.LABEL] = 0
            write_training(path, rows)
            with self.assertRaises(ValueError):
                mlsat.read_records(path)


class ModularRankTests(unittest.TestCase):
    def test_rank_changes_with_characteristic(self):
        matrix = [[2, 0], [0, 1]]
        original = deepcopy(matrix)
        self.assertEqual(mlsat.rank_mod(matrix, 2), 1)
        self.assertEqual(mlsat.rank_mod(matrix, 3), 2)
        self.assertEqual(matrix, original)

    def test_dependent_rectangular_negative_and_empty_rows(self):
        for prime in (2, 3):
            self.assertEqual(mlsat.rank_mod([[1, 2, -1], [2, 4, -2]], prime), 1)
            self.assertEqual(mlsat.rank_mod([], prime), 0)
            self.assertEqual(mlsat.rank_mod([[], []], prime), 0)
            self.assertEqual(mlsat.rank_mod([[0, 1], [1, 0], [1, 1]], prime), 2)


@unittest.skipUnless(HAS_NUMPY, "NumPy is an optional model dependency")
class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {"matching": rectangle_matching()}
        self.trace = {"active_generators": [1, 2, 3],
                      "relators": [[1, 1], [2, -3], [2, 3, 2, 3]]}

    def test_155_features_and_known_structural_invariants(self):
        original_candidate, original_trace = deepcopy(self.candidate), deepcopy(self.trace)
        features = mlsat.extract_features(self.candidate, self.trace)
        manifest = json.loads((ROOT / "models/training_manifest.json").read_text())
        self.assertEqual(sorted(features), manifest["feature_names"])
        self.assertEqual(len(features), 155)
        self.assertTrue(all(math.isfinite(value) for value in features.values()))
        self.assertEqual(features["positive_slope"], .5)
        self.assertEqual(features["row_distance_mean"], 1)
        self.assertEqual(features["col_distance_mean"], 1)
        self.assertEqual(features["letters"], 8)
        self.assertEqual(features["proper_power_relators"], 2)
        self.assertEqual(features["abelian_rank_mod2"], 2)
        self.assertEqual(features["abelian_rank_mod3"], 0)
        self.assertEqual(self.candidate, original_candidate)
        self.assertEqual(self.trace, original_trace)

    def test_rejects_repeated_cells_and_inactive_generators(self):
        bad = deepcopy(self.candidate)
        bad["matching"][-1] = bad["matching"][0]
        with self.assertRaises(ValueError):
            mlsat.extract_features(bad, self.trace)
        bad_trace = deepcopy(self.trace)
        bad_trace["relators"].append([4])
        with self.assertRaises(ValueError):
            mlsat.extract_features(self.candidate, bad_trace)


@unittest.skipUnless(HAS_SKLEARN, "Scikit-learn is an optional model dependency")
class LearningTests(unittest.TestCase):
    def test_same_matching_never_crosses_train_and_holdout(self):
        import numpy as np
        rows = [{"matching_sha256": f"{group:064x}", mlsat.LABEL: group % 2,
                 "features": {"group": float(group)}} for group in range(12) for _ in range(2)]
        observed = {}

        class Model:
            classes_ = [0, 1]

            def predict_proba(self, vectors):
                observed["test"] = {int(vector[0]) for vector in vectors}
                return np.array([[.4, .6] for _ in vectors])

        def fit(train, names):
            observed["train"] = {int(row["features"]["group"]) for row in train}
            return Model()

        with patch.object(mlsat, "fit", side_effect=fit):
            result = mlsat.evaluate(rows, ["group"], seed=22)
        self.assertFalse(observed["train"] & observed["test"])
        self.assertEqual(observed["train"] | observed["test"], set(range(12)))
        self.assertEqual(result["train_samples"], 2 * len(observed["train"]))
        self.assertEqual(result["test_samples"], 2 * len(observed["test"]))

    def test_tiny_fit_and_rank_cli_keep_bounded_label(self):
        rows = tiny_records()
        names = ["count", "signal"]
        fitted = mlsat.fit(rows, names)
        probabilities = fitted.predict_proba([[0, -1], [0, 1]])
        column = list(fitted.classes_).index(1)
        self.assertLess(probabilities[0, column], probabilities[1, column])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training, candidates, output = root / "training.json", root / "candidates.json", root / "ranking.json"
            write_training(training, rows)
            candidates.write_text(json.dumps([
                {"candidate_sha256": "a" * 64, "features": rows[0]["features"]},
                {"candidate_sha256": "b" * 64, "features": rows[-1]["features"]},
            ]))
            with redirect_stdout(io.StringIO()):
                mlsat.main(["rank", "--training", str(training), "--candidates", str(candidates),
                            "--output", str(output)])
            ranking = json.loads(output.read_text())
            self.assertEqual(ranking["format"], "k22-ml-ranking-v1")
            self.assertEqual(ranking["training_table_sha256"], hashlib.sha256(training.read_bytes()).hexdigest())
            self.assertEqual(ranking["ranking"][0]["candidate_sha256"], "b" * 64)
            self.assertIn("not torsion-freedom", ranking["warning"])
            self.assertTrue(all(0 <= row["score_old_bounded_unknown"] <= 1 for row in ranking["ranking"]))


@unittest.skipUnless(HAS_Z3, "Z3 is an optional model dependency")
class SATTests(unittest.TestCase):
    def test_two_proposals_are_distinct_complete_and_avoid_known_core(self):
        from models.common import Problem, fingerprint, edge_key
        from k22.verifier import image_index_digest
        support = [[[i, 0, 0], [1, sign, 1]] for i in range(11) for sign in (1, -1)]
        family = {"format": "k22-family-v1", "family_id": "fixture22", "n": 22, "m": 22,
                  "left": support, "right": support,
                  "image_index_sha256": image_index_digest(support, support)}
        matching = rectangle_matching()
        core = matching[24:26]
        problem = Problem(family, [{"matching": matching, "optional_core": core}])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(mlsat, "load_problem", return_value=problem), redirect_stdout(io.StringIO()):
                mlsat.main(["generate", "--count", "2", "--seed", "22", "--output", str(output)])
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["generated"], 2)
            self.assertEqual(summary["status"], "UNPROVED_CANDIDATES")
            ids = set()
            for path in sorted(output.glob("candidate_*.json")):
                candidate = json.loads(path.read_text())
                cells = [tuple(cell) for edge in candidate["matching"] for cell in edge]
                self.assertEqual(len(cells), 484)
                self.assertEqual(len(set(cells)), 484)
                self.assertEqual(problem.score(problem.encode(candidate["matching"]))["known_core_violations"], 0)
                self.assertFalse(set(map(edge_key, core)) <= set(map(edge_key, candidate["matching"])))
                self.assertEqual(candidate["candidate_sha256"], fingerprint({
                    "family_sha256": problem.family_sha256, "matching": candidate["matching"]}))
                ids.add(candidate["candidate_sha256"])
            self.assertEqual(len(ids), 2)


if __name__ == "__main__":
    unittest.main()
