"""Fixture integrity and the proof/verification/feedback integration boundary."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from discovery.cycle import advance_run, demo_run, load_memory, read_state, start_run
from k22.verifier import IDENTITY, VerificationError, inverse_image, multiply, verify_dataset, verify_family
from models.common import fingerprint


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "llm_demo"
DEMO_CORE_ID = "3790f085a9b33d1bc998777a9c18c044b73bc2faafe639bd5a9017a5b60d51db"
OTHER_KNOWN_CORE_ID = "c8931aa4420f06e0b5e9d4b687c2a0635518757207152e391b2b21f972646b13"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class DemoFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidate = read(FIXTURES / "candidate.json")
        cls.proposal = read(FIXTURES / "proposal.json")
        cls.original = read(ROOT / "data" / "submissions" / f"{DEMO_CORE_ID}.json")
        cls.family = verify_family(read(ROOT / "data" / "families" / "trinomial22.json"))

    def test_exact_source_order_and_fingerprints(self):
        candidate = self.candidate
        self.assertEqual(candidate["matching"], self.original["matching"])
        self.assertEqual(candidate["family_sha256"], self.family.sha256)
        self.assertEqual(candidate["image_index_sha256"], self.family.data["image_index_sha256"])
        self.assertEqual(candidate["candidate_sha256"], fingerprint({
            "family_sha256": self.family.sha256, "matching": candidate["matching"]}))
        self.assertEqual(self.proposal["candidate_sha256"], candidate["candidate_sha256"])

    def test_full_compatible_matching(self):
        matching = self.candidate["matching"]
        self.assertEqual(len(matching), 242)
        self.assertEqual({tuple(cell) for edge in matching for cell in edge},
                         {(i, j) for i in range(1, 23) for j in range(1, 23)})
        for left, right in matching:
            self.assertEqual(self.family.products[tuple(left)], self.family.products[tuple(right)])

    def test_hints_are_bound_to_original_relators_without_a_proof(self):
        self.assertEqual(set(self.proposal), {"format", "candidate_sha256", "targets"})
        self.assertEqual(self.proposal["format"], "k22-llm-proposal-v1")
        target, = self.proposal["targets"]
        self.assertEqual(target["word"], [23, -40])
        self.assertEqual(target["power"], 2)
        self.assertEqual(target["preferred_relators"], [200, 211])
        self.assertIn("Hand-authored DEMO", target["reason"])
        self.assertEqual(self.candidate["matching"][199], [[16, 1], [22, 18]])
        self.assertEqual(self.candidate["matching"][210], [[16, 18], [22, 1]])
        for payload in (self.candidate, self.proposal):
            encoded = json.dumps(payload)
            self.assertNotIn('"certificate"', encoded)
            self.assertNotIn('"nodes"', encoded)

    def test_target_has_nontrivial_affine_image(self):
        # Only the nonidentity witness is established here. This is not a
        # substitute for proving the power relation in the source group.
        value = IDENTITY
        for letter in self.proposal["targets"][0]["word"]:
            image = self.family.images[abs(letter) - 1]
            value = multiply(value, image if letter > 0 else inverse_image(image))
        self.assertNotEqual(value, IDENTITY)
        self.assertEqual(multiply(value, value), IDENTITY)

    def test_holdout_does_not_make_candidate_previously_uncovered(self):
        other = read(ROOT / "data" / "submissions" / f"{OTHER_KNOWN_CORE_ID}.json")
        edges = {tuple(sorted(map(tuple, edge))) for edge in self.candidate["matching"]}
        for known in (self.original, other):
            self.assertTrue({tuple(sorted(map(tuple, edge))) for edge in known["optional_core"]} <= edges)
        self.assertNotEqual(DEMO_CORE_ID, OTHER_KNOWN_CORE_ID)


class ChatCycleIntegrationTests(unittest.TestCase):
    """Small checked atlas; no paid calls, broad search, or shared outputs."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="k22-cycle-test-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.data = self.folder / "data"
        self.run = self.folder / "run"
        (self.data / "families").mkdir(parents=True)
        (self.data / "submissions").mkdir()
        family_path = ROOT / "data" / "families" / "trinomial22.json"
        (self.data / "families" / family_path.name).write_bytes(family_path.read_bytes())
        for sid in (DEMO_CORE_ID, OTHER_KNOWN_CORE_ID):
            source = ROOT / "data" / "submissions" / f"{sid}.json"
            (self.data / "submissions" / source.name).write_bytes(source.read_bytes())

    def start(self, **overrides):
        options = dict(data=self.data, rounds=1, population=8, epochs=1,
                       max_operations=1000, max_rules=1000, max_seconds=2,
                       candidate=FIXTURES / "candidate.json")
        options.update(overrides)
        return start_run(self.run, **options)

    def write_proposal(self, value, name="proposal.json"):
        path = self.folder / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def empty_proposal(self, candidate_hash):
        return {"format": "k22-llm-proposal-v1", "candidate_sha256": candidate_hash,
                "targets": []}

    def assert_no_feedback(self):
        self.assertEqual(list((self.run / "verified" / "submissions").glob("*.json")), [])

    def test_offline_demo_proves_replays_and_adds_exactly_one_known_core(self):
        seed_files = {p.relative_to(self.data): p.read_bytes() for p in self.data.rglob("*.json")}
        with patch("socket.create_connection", side_effect=AssertionError("No network in a chat/file demo")):
            result = demo_run(self.run, data=self.data)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["demo"])
        self.assertEqual(result["certified_attempts"], 1)
        self.assertEqual(result["new_cores_relative_to_run"], 1)
        self.assertEqual(result["new_cores_relative_to_input_atlas"], 0)
        self.assertIs(type(result["post_feedback_candidate_generated"]), bool)
        state = read_state(self.run)
        record, = state["history"]
        self.assertTrue(record["added_to_memory"])
        self.assertEqual(record["submission_id"], DEMO_CORE_ID)
        self.assertEqual(record["core_count_after"], record["core_count_before"] + 1)
        generation = read(self.run / "round_001" / "generation.json")
        self.assertGreaterEqual(generation["known_core_violations"], 1)
        report = verify_dataset(self.run / "verified")
        self.assertEqual(report["submissions"], 1)
        # Standalone replay in a fresh process does not trust engine return flags.
        check = subprocess.run([sys.executable, "-m", "k22", "verify", "--data", str(self.run / "verified")],
                               cwd=ROOT, capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        for name, contents in seed_files.items():
            self.assertEqual((self.data / name).read_bytes(), contents)

    def test_wrong_candidate_proposal_does_not_search_or_change_state(self):
        self.start()
        before = (self.run / "state.json").read_bytes()
        proposal = read(FIXTURES / "proposal.json")
        proposal["candidate_sha256"] = "0" * 64
        with patch("discovery.cycle.search", side_effect=AssertionError("Invalid proposals cannot launch search")):
            with self.assertRaises(ValueError):
                advance_run(self.run, self.write_proposal(proposal))
        self.assertEqual((self.run / "state.json").read_bytes(), before)
        self.assertFalse((self.run / "round_001" / "accepted_proposal.json").exists())
        self.assertFalse((self.run / "cycle.lock").exists())
        self.assert_no_feedback()

    def test_changed_saved_candidate_cannot_be_advanced(self):
        self.start()
        before = (self.run / "state.json").read_bytes()
        path = self.run / "round_001" / "candidate.json"
        value = read(path)
        value["matching"][0], value["matching"][1] = value["matching"][1], value["matching"][0]
        path.write_text(json.dumps(value), encoding="utf-8")
        with patch("discovery.cycle.search", side_effect=AssertionError("Changed candidates cannot launch search")):
            with self.assertRaises(ValueError):
                advance_run(self.run, FIXTURES / "proposal.json")
        self.assertEqual((self.run / "state.json").read_bytes(), before)
        self.assert_no_feedback()

    def test_forged_success_flag_cannot_add_feedback(self):
        self.start(demo=True)
        before = (self.run / "state.json").read_bytes()
        certificate = deepcopy(read(ROOT / "data" / "submissions" / f"{DEMO_CORE_ID}.json")["certificate"])
        certificate["target_word"] = [23]
        forged = {"status": "CERTIFIED_SOURCE_TORSION", "certificate": certificate}
        with patch("discovery.cycle.search", return_value=forged):
            with self.assertRaises(VerificationError):
                advance_run(self.run, FIXTURES / "proposal.json")
        self.assertEqual((self.run / "state.json").read_bytes(), before)
        self.assert_no_feedback()
        self.assertFalse((self.run / "round_001" / "verification.json").exists())

    def test_duplicate_verified_core_is_not_added_again(self):
        self.start()
        result = advance_run(self.run, FIXTURES / "proposal.json")
        self.assertEqual(result["certified_attempts"], 1)
        self.assertEqual(result["new_cores_relative_to_run"], 0)
        self.assertEqual(result["new_cores_relative_to_input_atlas"], 0)
        record, = read_state(self.run)["history"]
        self.assertEqual(record["novelty"], "KNOWN_CORE")
        self.assertFalse(record["added_to_memory"])
        self.assertEqual(record["core_count_before"], record["core_count_after"])
        self.assert_no_feedback()

    def test_empty_proposals_advance_as_unknown_and_stale_proposals_fail(self):
        self.start(rounds=2)
        state = read_state(self.run)
        first = self.write_proposal(self.empty_proposal(state["current_candidate_sha256"]), "first.json")
        result = advance_run(self.run, first)
        self.assertEqual(result["status"], "AWAITING_PROPOSAL")
        self.assertEqual(result["completed_rounds"], 1)
        self.assertEqual(result["outcomes"], {"UNKNOWN": 1})
        state = read_state(self.run)
        self.assertEqual(state["round_index"], 2)
        self.assertNotEqual(state["current_candidate_sha256"], read(first)["candidate_sha256"])
        before = (self.run / "state.json").read_bytes()
        with self.assertRaises(ValueError):
            advance_run(self.run, first)
        self.assertEqual((self.run / "state.json").read_bytes(), before)
        second = self.write_proposal(self.empty_proposal(state["current_candidate_sha256"]), "second.json")
        result = advance_run(self.run, second)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["outcomes"], {"UNKNOWN": 2})
        self.assertEqual(result["new_cores_relative_to_run"], 0)
        self.assert_no_feedback()
        with self.assertRaises(ValueError):
            advance_run(self.run, second)
        self.assertEqual(len(read_state(self.run)["history"]), 2)

    def test_operation_bound_remains_unknown_without_feedback(self):
        self.start(demo=True, max_operations=1)
        result = advance_run(self.run, FIXTURES / "proposal.json")
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["outcomes"], {"UNKNOWN": 1})
        self.assertEqual(result["certified_attempts"], 0)
        self.assertEqual(result["new_cores_relative_to_run"], 0)
        self.assert_no_feedback()
        search_result = read(self.run / "round_001" / "search.json")
        self.assertEqual(search_result["stop_reason"], "max_operations")
        self.assertLessEqual(search_result["metrics"]["operations"], 1)

    def test_state_types_and_structure_cannot_be_forged(self):
        self.start()
        path = self.run / "state.json"
        original = path.read_bytes()
        state = read(path)
        alterations = [
            lambda s: s.update(round_index=True),
            lambda s: s.update(demo="false"),
            lambda s: s.update(history="not a history"),
            lambda s: s.update(status="TORSION_FREE"),
            lambda s: s["config"].update(rounds=True),
            lambda s: s["config"].update(unrecognized_execution_hook="ignored"),
        ]
        for alter in alterations:
            value = deepcopy(state)
            alter(value)
            with self.subTest(alteration=value):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises((ValueError, OSError)):
                    read_state(self.run)
            path.write_bytes(original)
        self.assertEqual(read_state(self.run)["history"], [])

    def test_current_state_hash_must_match_the_saved_candidate(self):
        self.start()
        path = self.run / "state.json"
        state = read(path)
        state["current_candidate_sha256"] = "0" * 64
        path.write_text(json.dumps(state), encoding="utf-8")
        # Even a proposal bound to the forged state hash cannot redirect the
        # hypothesis away from the actual candidate that was generated.
        proposal = read(FIXTURES / "proposal.json")
        proposal["candidate_sha256"] = "0" * 64
        with patch("discovery.cycle.search", side_effect=AssertionError("Hash mismatch cannot launch search")):
            with self.assertRaises(ValueError):
                advance_run(self.run, self.write_proposal(proposal))
        self.assert_no_feedback()

    def test_oversized_state_is_rejected(self):
        self.start()
        (self.run / "state.json").write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            read_state(self.run)
        self.assert_no_feedback()

    def test_certified_history_counters_require_replayed_evidence(self):
        self.start(demo=True)
        advance_run(self.run, FIXTURES / "proposal.json")
        path = self.run / "state.json"
        original = path.read_bytes()
        state = read(path)
        alterations = [
            lambda r: r.update(added_to_memory=False),
            lambda r: r.update(core_count_after=r["core_count_after"] + 1),
            lambda r: r.update(optional_core_edges=r["optional_core_edges"] + 1),
            lambda r: r.update(power_divides=True),
            lambda r: r.update(submission_id=OTHER_KNOWN_CORE_ID),
        ]
        for alter in alterations:
            value = deepcopy(state)
            alter(value["history"][0])
            with self.subTest(record=value["history"][0]):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises((ValueError, OSError)):
                    read_state(self.run)
            path.write_bytes(original)
        self.assertTrue(read_state(self.run)["history"][0]["added_to_memory"])

    def test_changed_round_certificate_invalidates_saved_success(self):
        self.start(demo=True)
        advance_run(self.run, FIXTURES / "proposal.json")
        path = self.run / "round_001" / "submission.json"
        submission = read(path)
        submission["certificate"]["target_word"] = [23]
        path.write_text(json.dumps(submission), encoding="utf-8")
        with self.assertRaises((ValueError, OSError)):
            read_state(self.run)

    def test_missing_admitted_memory_invalidates_history(self):
        self.start(demo=True)
        advance_run(self.run, FIXTURES / "proposal.json")
        path = self.run / "verified" / "submissions" / f"{DEMO_CORE_ID}.json"
        path.unlink()
        with self.assertRaises((ValueError, OSError)):
            read_state(self.run)

    def test_existing_lock_is_preserved_and_blocks_another_advance(self):
        self.start()
        lock = self.run / "cycle.lock"
        lock.write_text("other active process", encoding="utf-8")
        before = (self.run / "state.json").read_bytes()
        with self.assertRaises(ValueError):
            advance_run(self.run, FIXTURES / "proposal.json")
        self.assertEqual(lock.read_text(encoding="utf-8"), "other active process")
        self.assertEqual((self.run / "state.json").read_bytes(), before)

    def test_uncommitted_feedback_after_a_crash_does_not_erase_novelty_on_retry(self):
        self.start(demo=True)
        feedback = self.run / "verified"
        (feedback / "families").mkdir(parents=True)
        (feedback / "submissions").mkdir()
        (feedback / "families" / "trinomial22.json").write_bytes(
            (self.data / "families" / "trinomial22.json").read_bytes())
        # Simulate a valid proof written before a process dies at state commit.
        # This is an integration recovery fixture, not input to proof search.
        (feedback / "submissions" / f"{DEMO_CORE_ID}.json").write_bytes(
            (self.data / "submissions" / f"{DEMO_CORE_ID}.json").read_bytes())
        before = read_state(self.run)
        self.assertEqual(before["history"], [])
        memory = load_memory(self.run, before)
        self.assertNotIn(DEMO_CORE_ID, {s["submission_id"] for s in memory.submissions})
        result = advance_run(self.run, FIXTURES / "proposal.json")
        self.assertEqual(result["new_cores_relative_to_run"], 1)
        self.assertEqual(result["new_cores_relative_to_input_atlas"], 0)
        after = read_state(self.run)
        self.assertTrue(after["history"][0]["added_to_memory"])
        self.assertEqual(sum(s["submission_id"] == DEMO_CORE_ID
                             for s in load_memory(self.run, after).submissions), 1)


if __name__ == "__main__":
    unittest.main()
