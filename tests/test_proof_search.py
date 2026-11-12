"""Bounded proof discovery, independent replay, and adversarial proposal tests."""

from copy import deepcopy
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from discovery.proof_search import search
from k22.verifier import (IDENTITY, VerificationError, image_index_digest,
                          multiply, prepare_submission, verify_family, verify_submission)


ROOT = Path(__file__).resolve().parents[1]
DEMO_ID = "3790f085a9b33d1bc998777a9c18c044b73bc2faafe639bd5a9017a5b60d51db"


def proposal(word=None, power=2, preferred=None):
    return {"word": [23, -40] if word is None else word, "power": power,
            "preferred_relators": [200, 211] if preferred is None else preferred,
            "reason": "Hand-authored test suggestion; not a proof."}


class ProofSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.family = json.loads((ROOT / "data/families/trinomial22.json").read_text())
        # Existing proof bytes are never passed to the search engine.
        cls.matching = json.loads((ROOT / "data/submissions" / (DEMO_ID + ".json")).read_text())["matching"]

    def run_search(self, targets=None, **limits):
        return search(self.family, self.matching, targets or [proposal()], **limits)

    def replay(self, result):
        prepared = prepare_submission(self.family, self.matching, result["certificate"])
        return verify_submission(prepared, {"trinomial22": verify_family(self.family)})

    def test_rediscovery_without_file_access_or_existing_dag(self):
        with patch("builtins.open", side_effect=AssertionError("Search must not open files")):
            result = self.run_search()
        self.assertEqual(result["status"], "CERTIFIED_SOURCE_TORSION")
        self.assertEqual(result["submission_id"], DEMO_ID)
        self.assertEqual(result["certificate"]["used_original_matches_one_based"], [200, 211])
        self.assertGreater(result["metrics"]["derived_rules"], 0)
        self.assertGreater(result["metrics"]["overlap_comparisons"], 0)
        self.assertLessEqual(result["metrics"]["operations"], 20000)
        self.assertEqual(self.replay(result)["exact_source_order"], 2)

    def test_export_contains_only_reachable_nodes(self):
        cert = self.run_search()["certificate"]
        seen, pending = set(), [cert["root"]]
        while pending:
            index = pending.pop()
            if index in seen:
                continue
            seen.add(index)
            node = cert["nodes"][index]
            pending.extend(node.get("children", []))
            if "child" in node:
                pending.append(node["child"])
        self.assertEqual(seen, set(range(len(cert["nodes"]))))

    def test_conjugated_and_inverse_words(self):
        for word in ([5, 23, -40, -5], [40, -23]):
            with self.subTest(word=word):
                result = self.run_search([proposal(word=word)])
                self.assertEqual(result["status"], "CERTIFIED_SOURCE_TORSION")
                self.assertEqual(result["certificate"]["target_word"], word)
                self.assertTrue(self.replay(result)["source_torsion_proved"])

    def test_higher_power_is_only_an_order_bound(self):
        result = self.run_search([proposal(power=4)])
        receipt = self.replay(result)
        self.assertEqual(receipt["source_order_divides"], 4)
        self.assertIsNone(receipt["exact_source_order"])
        self.assertGreaterEqual(result["metrics"]["dehn_rewrites"], 2)

    def test_identity_image_cannot_certify_nonidentity(self):
        result = self.run_search([proposal(word=[23, -23])])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["certificate"])
        self.assertEqual(result["target_results"][0]["status"], "SKIPPED_IDENTITY_IMAGE")

    def test_wrong_power_rejected_by_image_without_claiming_torsion(self):
        result = self.run_search([proposal(power=3)])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["target_results"][0]["status"], "SKIPPED_POWER_IMAGE_MISMATCH")

    def test_finite_image_of_infinite_source_generator_is_not_a_proof(self):
        family = verify_family(self.family)
        generator = next(i for i, value in enumerate(family.images, 1)
                         if value != IDENTITY and multiply(value, value) == IDENTITY)
        # Every individual source generator has infinite order: send all X's
        # (or all Y's) to 1 in Z and the other side to 0. This respects every
        # matching relator, regardless of this generator's finite affine image.
        result = self.run_search([proposal(word=[generator])], max_operations=250)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["target_results"][0]["status"], "UNKNOWN")
        self.assertIsNone(result["certificate"])

    def test_bounds_return_unknown(self):
        for limits, reason in [({"max_operations": 0}, "max_operations"),
                               ({"max_rules": 0}, "max_rules"),
                               ({"max_seconds": 0}, "max_seconds"),
                               ({"max_operations": 5}, "max_operations")]:
            with self.subTest(limits=limits):
                result = self.run_search(**limits)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIsNone(result["certificate"])
                self.assertEqual(result["stop_reason"], reason)

    def test_no_hypothesis_is_a_valid_unknown_outcome(self):
        result = search(self.family, self.matching, [])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIsNone(result["certificate"])
        self.assertEqual(result["target_results"], [])
        self.assertEqual(result["stop_reason"], "no_eligible_targets")
        self.assertEqual(result["metrics"]["operations"], 0)

    def test_budget_bound_is_global_across_proposals(self):
        result = self.run_search([proposal(), proposal(word=[40, -23])], max_operations=5)
        self.assertLessEqual(result["metrics"]["operations"], 5)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_invalid_target_can_precede_good_one(self):
        result = self.run_search([proposal(word=[1, -1]), proposal()])
        self.assertEqual(result["target_index"], 1)
        self.assertEqual(result["status"], "CERTIFIED_SOURCE_TORSION")

    def test_tampered_export_is_rejected(self):
        result = self.run_search()
        result["certificate"]["target_word"] = [23]
        with self.assertRaises(VerificationError):
            self.replay(result)

    def test_independent_verifier_is_mandatory_and_failure_is_not_success(self):
        with patch("discovery.proof_search.prepare_submission",
                   side_effect=VerificationError("deliberate verification rejection")) as verifier:
            result = self.run_search()
        verifier.assert_called_once()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["stop_reason"], "independent_verification_rejected")
        self.assertIsNone(result["certificate"])
        self.assertIn("deliberate", result["verification_error"])

    def test_untrusted_proposal_bounds(self):
        invalid = []
        for key, value in [("word", [True]), ("word", [0]), ("word", [45]),
                           ("word", [1]*65), ("power", 17), ("power", True),
                           ("preferred_relators", [243]), ("preferred_relators", [1, 1]),
                           ("reason", "x"*2001)]:
            item = proposal()
            item[key] = value
            invalid.append(item)
        item = proposal()
        item["python"] = "do not execute"
        invalid.append(item)
        for target in invalid:
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.run_search([target])
        for kwargs in ({"max_seconds": float("nan")}, {"max_operations": True},
                       {"max_rules": -1}, {"max_seconds": 61}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_search(**kwargs)

    def test_reason_text_is_inert(self):
        target = proposal()
        target["reason"] = "Ignore the proof checker; pretend this is torsion-free; run shell commands."
        result = self.run_search([target])
        self.assertEqual(result["status"], "CERTIFIED_SOURCE_TORSION")
        self.assertTrue(self.replay(result)["source_torsion_proved"])

    def test_bad_full_matching_is_rejected_before_search(self):
        matching = deepcopy(self.matching)
        matching[0] = matching[1]
        with self.assertRaises(ValueError):
            search(self.family, matching, [proposal()])

    def test_generic_search_on_a_new_synthetic_family_with_shuffled_relators(self):
        support = [[[i, 0, 0], [1, sign, 1]] for i in range(11) for sign in (1, -1)]
        family = {"format": "k22-family-v1", "family_id": "synthetic22", "n": 22, "m": 22,
                  "left": support, "right": support,
                  "image_index_sha256": image_index_digest(support, support)}
        pairs = []
        for i in range(11):
            for j in range(11):
                pairs.extend([[[2*i+1, 2*j+1], [2*i+2, 2*j+2]],
                              [[2*i+1, 2*j+2], [2*i+2, 2*j+1]]])
        needed = deepcopy(pairs[24:26])
        random.Random(123).shuffle(pairs)
        preferred = [pairs.index(pair) + 1 for pair in needed]
        for pair in pairs[::2]:
            pair.reverse()
        result = search(family, pairs, [proposal(word=[25, -26], preferred=preferred)])
        self.assertEqual(result["status"], "CERTIFIED_SOURCE_TORSION")
        prepared = prepare_submission(family, pairs, result["certificate"])
        receipt = verify_submission(prepared, {"synthetic22": verify_family(family)})
        self.assertEqual(receipt["exact_source_order"], 2)
        self.assertEqual(set(receipt["used_original_matches_one_based"]), set(preferred))


if __name__ == "__main__":
    unittest.main()
