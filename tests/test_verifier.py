"""Mathematical and hostile-input tests, using an independently built fixture."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from k22.verifier import (DEFAULT_LIMITS, VerificationError, canonical_bytes,
                          digest, image_index_digest, prepare_submission, read_json, verify_dataset,
                          verify_family, verify_submission)


def fixture():
    # C2 x Z affine images: translate coordinate 1 and reflect coordinate 2.
    support = [[[i, 0, 0], [1, sign, 1]] for i in range(11) for sign in (1, -1)]
    family = {"format": "k22-family-v1", "family_id": "test22", "n": 22, "m": 22,
              "left": support, "right": deepcopy(support),
              "image_index_sha256": image_index_digest(support, support)}
    matching = []
    for i in range(11):
        for j in range(11):
            matching.extend([[[2*i+1, 2*j+1], [2*i+2, 2*j+2]],
                             [[2*i+1, 2*j+2], [2*i+2, 2*j+1]]])
    # Match 25: X3 Y3 = X4 Y4. Match 26: X3 Y4 = X4 Y3.
    # X3^-1 (r25 r26^-1) X3 = (Y3 Y4^-1)^2.
    certificate = {"format": "k22-normal-closure-dag-v1", "target_word": [25, -26],
                   "power": 2, "nodes": [{"op": "match", "match": 25},
                   {"op": "match", "match": 26}, {"op": "inverse", "child": 1},
                   {"op": "product", "children": [0, 2]},
                   {"op": "conjugate", "child": 3, "conjugator": [-3]}],
                   "root": 4, "used_original_matches_one_based": [25, 26],
                   "expanded_original_relator_factor_count": 2}
    core = matching[24:26]
    sha = digest(family)
    submission = {"format": "k22-submission-v1", "family_id": "test22",
                  "family_sha256": sha, "image_index_sha256": family["image_index_sha256"],
                  "matching": matching, "optional_core": core, "certificate": certificate,
                  "submission_id": digest({"family_sha256": sha, "optional_core": core})}
    return family, submission


def refresh_id(submission):
    submission["submission_id"] = digest({"family_sha256": submission["family_sha256"],
                                          "optional_core": submission["optional_core"]})


def save_dataset(root, family, submission):
    (root / "families").mkdir()
    (root / "submissions").mkdir()
    (root / "families" / (family["family_id"] + ".json")).write_bytes(canonical_bytes(family))
    path = root / "submissions" / (submission["submission_id"] + ".json")
    path.write_bytes(canonical_bytes(submission))
    return path


class MathematicalTests(unittest.TestCase):
    def setUp(self):
        self.family, self.submission = fixture()
        self.families = {"test22": verify_family(self.family)}

    def check(self, limits=DEFAULT_LIMITS):
        return verify_submission(self.submission, self.families, limits)

    def rejected(self, message):
        with self.assertRaisesRegex(VerificationError, message):
            self.check()

    def test_genuine_nonidentity_order_two_proof(self):
        result = self.check()
        self.assertTrue(result["source_torsion_proved"])
        self.assertEqual(result["exact_source_order"], 2)
        self.assertEqual(result["optional_core_edges"], 2)
        self.assertEqual(result["forced_pairs"], 4)

    def test_prepare_derives_exact_core_and_replays(self):
        prepared = prepare_submission(self.family, self.submission["matching"], self.submission["certificate"])
        self.assertEqual(prepared, self.submission)
        self.submission["certificate"]["power"] = 3
        with self.assertRaisesRegex(VerificationError, "root is not target"):
            prepare_submission(self.family, self.submission["matching"], self.submission["certificate"])

    def test_higher_power_does_not_claim_exact_order(self):
        cert = self.submission["certificate"]
        cert["nodes"].append({"op": "product", "children": [4, 4]})
        cert.update(root=5, power=4, expanded_original_relator_factor_count=4)
        result = self.check()
        self.assertEqual(result["source_order_divides"], 4)
        self.assertIsNone(result["exact_source_order"])

    def test_nontriviality_required_even_for_valid_normal_closure_proof(self):
        cert = self.submission["certificate"]
        # A relator itself has image 1; its square is a legitimate consequence.
        cert["target_word"] = [3, 25, -26, -4]
        cert["nodes"] = [{"op": "match", "match": 25}, {"op": "product", "children": [0, 0]}]
        cert.update(root=1, used_original_matches_one_based=[25])
        self.submission["optional_core"] = [self.submission["matching"][24]]
        refresh_id(self.submission)
        self.rejected("nonidentity is not certified")

    def test_finite_image_alone_is_not_a_torsion_proof(self):
        self.submission["certificate"]["target_word"] = [23, -24]
        self.rejected("root is not target")

    def test_tampered_power(self):
        self.submission["certificate"]["power"] = 3
        self.rejected("root is not target")

    def test_tampered_conjugation(self):
        self.submission["certificate"]["nodes"][4]["conjugator"] = [3]
        self.rejected("root is not target")

    def test_tampered_matching_orientation(self):
        self.submission["matching"][24] = list(reversed(self.submission["matching"][24]))
        self.rejected("root is not target")

    def test_repeated_cell(self):
        self.submission["matching"][0] = self.submission["matching"][1]
        self.rejected("partition")

    def test_unequal_images_even_with_full_partition(self):
        a, b = self.submission["matching"][0], self.submission["matching"][2]
        a[1], b[1] = b[1], a[1]
        self.rejected("unequal affine images")

    def test_missing_core_leaf(self):
        self.submission["optional_core"] = self.submission["optional_core"][:1]
        refresh_id(self.submission)
        self.rejected("proof leaves")

    def test_extra_core_edge(self):
        self.submission["optional_core"].append(self.submission["matching"][26])
        self.submission["optional_core"].sort()
        refresh_id(self.submission)
        self.rejected("proof leaves")

    def test_forced_edge_cannot_be_claimed_optional(self):
        self.submission["optional_core"].insert(0, self.submission["matching"][0])
        refresh_id(self.submission)
        self.rejected("forced edge")

    def test_family_mixing(self):
        other = deepcopy(self.family)
        other["family_id"] = "other22"
        self.families["other22"] = verify_family(other)
        self.submission["family_id"] = "other22"
        self.rejected("family hash differs")

    def test_image_index_binding(self):
        self.submission["image_index_sha256"] = "0" * 64
        self.rejected("image index hash differs")

    def test_family_images_are_order_bound(self):
        self.family["left"][0], self.family["left"][1] = self.family["left"][1], self.family["left"][0]
        with self.assertRaisesRegex(VerificationError, "image index hash"):
            verify_family(self.family)

    def test_duplicate_support_image(self):
        self.family["left"][1] = self.family["left"][0]
        with self.assertRaisesRegex(VerificationError, "not distinct"):
            verify_family(self.family)

    def test_boolean_is_not_generator_integer(self):
        self.submission["certificate"]["target_word"] = [True]
        self.rejected("generator letter")

    def test_out_of_range_generator(self):
        self.submission["certificate"]["target_word"] = [45]
        self.rejected("generator letter")

    def test_forward_dag_reference(self):
        self.submission["certificate"]["nodes"][2]["child"] = 4
        self.rejected("DAG child")

    def test_unknown_dag_operation_is_not_executed(self):
        self.submission["certificate"]["nodes"][0] = {"op": "exec", "code": "raise Exception()"}
        self.rejected("unknown proof operation")

    def test_used_leaf_manifest_is_verified(self):
        self.submission["certificate"]["used_original_matches_one_based"] = [25]
        self.rejected("used-match manifest")

    def test_factor_count_is_verified(self):
        self.submission["certificate"]["expanded_original_relator_factor_count"] = 1
        self.rejected("factor count differs")

    def test_no_extra_path_field(self):
        self.submission["certificate"]["source"] = "../../outside.py"
        self.rejected("unexpected or missing fields")

    def test_traversal_family_id(self):
        self.submission["family_id"] = "../../outside"
        self.rejected("invalid family_id")

    def test_all_proof_budgets_are_enforced(self):
        for kwargs, message in [({"max_nodes": 4}, "node count"),
                                ({"max_work": 2}, "work budget"),
                                ({"max_node_word": 3}, "node word budget"),
                                ({"max_stored_letters": 3}, "stored word budget"),
                                ({"max_factor_bits": 1}, "factor count budget"),
                                ({"max_power": 1}, "power")]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(VerificationError, message):
                self.check(replace(DEFAULT_LIMITS, **kwargs))


class LoaderTests(unittest.TestCase):
    def test_prepare_cli(self):
        family, submission = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in [("family", family), ("matching", submission["matching"]),
                               ("certificate", submission["certificate"])]:
                (root / (name + ".json")).write_bytes(canonical_bytes(data))
            output = root / "output"
            output.mkdir()
            command = [sys.executable, "-m", "k22", "prepare", "--family", str(root / "family.json"),
                       "--matching", str(root / "matching.json"), "--certificate", str(root / "certificate.json"),
                       "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data, _ = read_json(output / (submission["submission_id"] + ".json"))
            self.assertEqual(data, submission)
            duplicate = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(duplicate.returncode, 1, "prepare must not silently overwrite an existing submission")

    def test_dataset_and_cli(self):
        family, submission = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dataset(root, family, submission)
            report = verify_dataset(root)
            self.assertEqual(report["submissions"], 1)
            result = subprocess.run([sys.executable, "-m", "k22", "verify", "--data", str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["submissions"], 1)

    def test_validation_survives_python_optimized_mode(self):
        family, submission = fixture()
        submission["certificate"]["power"] = 3
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dataset(root, family, submission)
            result = subprocess.run([sys.executable, "-O", "-m", "k22", "verify", "--data", str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("root is not target", result.stderr)

    def test_malicious_json_encodings(self):
        for content, message in [(b'{"x":1,"x":2}', "duplicate JSON key"),
                                 (b'{"x":NaN}', "nonfinite"),
                                 (b'{"x":1.0}', "floating point"),
                                 (b'{"x":' + b'1'*79 + b'}', "integer is too large"),
                                 (b'['*33 + b']'*33, "nesting budget"),
                                 (b'{"x":"\xff"}', "UTF-8")]:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "input.json"
                path.write_bytes(content)
                with self.assertRaisesRegex(VerificationError, message):
                    read_json(path)

    def test_file_size_and_dataset_limits(self):
        family, submission = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_dataset(root, family, submission)
            with self.assertRaisesRegex(VerificationError, "file size"):
                read_json(path, max_bytes=10)
            for kwargs, message in [({"max_submissions": 0}, "file count"),
                                    ({"max_total_bytes": 10}, "byte budget"),
                                    ({"max_dataset_work": 1}, "dataset work")]:
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(VerificationError, message):
                    verify_dataset(root, replace(DEFAULT_LIMITS, **kwargs))

    def test_filename_binding(self):
        family, submission = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_dataset(root, family, submission)
            path.rename(path.with_name("0"*64 + ".json"))
            with self.assertRaisesRegex(VerificationError, "filename differs"):
                verify_dataset(root)

    def test_nested_paths_are_not_followed(self):
        family, submission = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dataset(root, family, submission)
            (root / "submissions" / "nested").mkdir()
            with self.assertRaisesRegex(VerificationError, "unexpected data path"):
                verify_dataset(root)

    def test_symlink_not_followed(self):
        family, submission = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = save_dataset(root, family, submission)
            target = root / "elsewhere.json"
            path.rename(target)
            try:
                path.symlink_to(target)
            except OSError as error:
                self.skipTest(f"platform lacks symlink permission: {error}")
            with self.assertRaisesRegex(VerificationError, "symlink or reparse"):
                verify_dataset(root)


if __name__ == "__main__":
    unittest.main()
