"""Small independently proved fixtures for persisted-core dataset merging."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from discovery.data_merge import merge_data
from k22.verifier import (DEFAULT_LIMITS, VerificationError, canonical_bytes,
                         image_index_digest, prepare_submission, verify_dataset)


def fixture(block=1, scale=1):
    support = [[[scale * i, 0, 0], [1, sign, 1]] for i in range(11) for sign in (1, -1)]
    family = {"format": "k22-family-v1", "family_id": "merge22", "n": 22, "m": 22,
              "left": support, "right": deepcopy(support),
              "image_index_sha256": image_index_digest(support, support)}
    matching = []
    for i in range(1, 23, 2):
        for j in range(1, 23, 2):
            matching.extend([[[i, j], [i + 1, j + 1]], [[i, j + 1], [i + 1, j]]])
    row = column = 2 * block + 1
    first = 2 * (11 * block + block) + 1
    # X_row^-1 (r_first r_(first+1)^-1) X_row
    # is (Y_column Y_(column+1)^-1)^2. Its reflection image is nonidentity.
    certificate = {"format": "k22-normal-closure-dag-v1",
        "target_word": [22 + column, -23 - column], "power": 2,
        "nodes": [{"op": "match", "match": first}, {"op": "match", "match": first + 1},
                  {"op": "inverse", "child": 1}, {"op": "product", "children": [0, 2]},
                  {"op": "conjugate", "child": 3, "conjugator": [-row]}],
        "root": 4, "used_original_matches_one_based": [first, first + 1],
        "expanded_original_relator_factor_count": 2}
    return family, prepare_submission(family, matching, certificate)


def save(root, family, submissions):
    (root / "families").mkdir(parents=True)
    (root / "submissions").mkdir()
    (root / "families" / f"{family['family_id']}.json").write_bytes(canonical_bytes(family) + b"\n")
    for submission in submissions:
        (root / "submissions" / f"{submission['submission_id']}.json").write_bytes(canonical_bytes(submission) + b"\n")


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*.json")}


class DataMergeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.base, self.feedback, self.output = root / "base", root / "feedback", root / "merged"
        self.family, self.first = fixture(1)
        _, self.second = fixture(2)
        save(self.base, self.family, [self.first])

    def test_union_replays_and_keeps_both_inputs_unchanged(self):
        save(self.feedback, self.family, [self.second])
        before = snapshot(self.base), snapshot(self.feedback)
        self.output.mkdir()  # An explicitly empty destination is supported.
        result = merge_data(self.base, self.feedback, self.output)
        self.assertEqual(result["added_cores_relative_to_base"], 1)
        self.assertEqual(result["duplicate_core_ids"], 0)
        self.assertEqual(result["merged_cores"], 2)
        self.assertEqual(verify_dataset(self.output)["submissions"], 2)
        self.assertEqual((snapshot(self.base), snapshot(self.feedback)), before)

    def test_duplicate_id_prefers_base_certificate_without_increment(self):
        alternative = deepcopy(self.first)
        certificate = alternative["certificate"]
        certificate["nodes"].append({"op": "product", "children": [4, 4]})
        certificate.update(root=5, power=4, expanded_original_relator_factor_count=4)
        save(self.feedback, self.family, [alternative])
        verify_dataset(self.feedback)
        result = merge_data(self.base, self.feedback, self.output)
        self.assertEqual(result["duplicate_core_ids"], 1)
        self.assertEqual(result["added_cores_relative_to_base"], 0)
        self.assertEqual(result["merged_cores"], 1)
        stored = json.loads((self.output / "submissions" / f"{self.first['submission_id']}.json").read_bytes())
        self.assertEqual(stored, self.first)
        self.assertEqual(stored["certificate"]["power"], 2)

    def test_same_family_id_with_other_images_rejected_before_writing(self):
        family, submission = fixture(2, scale=2)
        save(self.feedback, family, [submission])
        verify_dataset(self.feedback)
        with self.assertRaisesRegex(VerificationError, "different ordered images"):
            merge_data(self.base, self.feedback, self.output)
        self.assertFalse(self.output.exists())

    def test_empty_feedback_rejected_before_writing(self):
        save(self.feedback, self.family, [])
        with self.assertRaisesRegex(VerificationError, "no submissions"):
            merge_data(self.base, self.feedback, self.output)
        self.assertFalse(self.output.exists())

    def test_nonempty_or_input_nested_output_never_modified(self):
        save(self.feedback, self.family, [self.second])
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("operator data")
        with self.assertRaises(VerificationError):
            merge_data(self.base, self.feedback, self.output)
        self.assertEqual(marker.read_text(), "operator data")
        with self.assertRaises(VerificationError):
            merge_data(self.base, self.feedback, self.base / "nested-output")
        self.assertFalse((self.base / "nested-output").exists())

    def test_union_limit_checked_before_any_output_writes(self):
        save(self.feedback, self.family, [self.second])
        limits = replace(DEFAULT_LIMITS, max_submissions=1)
        with patch("discovery.data_merge.DEFAULT_LIMITS", limits):
            with self.assertRaisesRegex(VerificationError, "Merged submission count"):
                merge_data(self.base, self.feedback, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
