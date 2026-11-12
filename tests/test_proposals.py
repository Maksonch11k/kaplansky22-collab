"""Strict, offline-only chat proposals and complete mathematical prompts."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from discovery.proposals import (FORMAT, MAX_PROPOSAL_BYTES, ProposalError,
                                 make_prompt, parse_json, proposal_schema,
                                 read_proposal, validate_proposal)
from k22.verifier import digest, image_index_digest


HASH = "a" * 64


def proposal():
    return {"format": FORMAT, "candidate_sha256": HASH, "targets": [
        {"word": [23, -24], "power": 2, "preferred_relators": [2, 1],
         "reason": "A hypothesis only; the exact checker must prove it."}]}


def family_candidate():
    support = [[[i, 0, 0], [1, sign, 1]] for i in range(11) for sign in (1, -1)]
    family = {"format": "k22-family-v1", "family_id": "test22", "n": 22, "m": 22,
              "left": support, "right": deepcopy(support),
              "image_index_sha256": image_index_digest(support, support)}
    matching = []
    for i in range(1, 23, 2):
        for j in range(1, 23, 2):
            matching.extend([[[i, j], [i + 1, j + 1]], [[i, j + 1], [i + 1, j]]])
    family_hash = digest(family)
    candidate = {"format": "k22-candidate-v1", "family_id": "test22",
                 "family_sha256": family_hash,
                 "image_index_sha256": family["image_index_sha256"],
                 "matching": matching, "status": "UNPROVED_CANDIDATE",
                 "candidate_sha256": digest({"family_sha256": family_hash, "matching": matching})}
    return family, candidate


class ProposalContractTests(unittest.TestCase):
    def test_round_trip_preserves_hint_order_and_copies_lists(self):
        raw = proposal()
        result = validate_proposal(raw, HASH)
        self.assertEqual(result, raw)
        result["targets"][0]["word"].append(1)
        result["targets"][0]["preferred_relators"].reverse()
        self.assertEqual(raw["targets"][0]["word"], [23, -24])
        self.assertEqual(raw["targets"][0]["preferred_relators"], [2, 1])

    def test_empty_targets_is_no_hypothesis_not_a_proof(self):
        raw = proposal()
        raw["targets"] = []
        self.assertEqual(validate_proposal(raw, HASH)["targets"], [])

    def test_exact_fields_and_format(self):
        mutations = [lambda x: x.update(extra=True), lambda x: x.pop("format"),
                     lambda x: x.update(format="other"),
                     lambda x: x["targets"][0].update(command="do not execute"),
                     lambda x: x["targets"][0].pop("reason")]
        for mutate in mutations:
            raw = proposal()
            mutate(raw)
            with self.subTest(mutation=mutate), self.assertRaises(ProposalError):
                validate_proposal(raw, HASH)

    def test_hash_must_be_valid_and_bound_to_expected_candidate(self):
        for expected in ("b" * 64, "A" * 64, "a" * 63, None, True):
            with self.subTest(expected=expected), self.assertRaises(ProposalError):
                validate_proposal(proposal(), expected)

    def test_signed_word_bounds_and_exact_integer_types(self):
        for word in ([], [0], [45], [-45], [True], [1.0], ["1"], [1] * 33):
            raw = proposal()
            raw["targets"][0]["word"] = word
            with self.subTest(word=word), self.assertRaises(ProposalError):
                validate_proposal(raw, HASH)
        raw = proposal()
        raw["targets"][0]["word"] = [-44, 44] * 16
        self.assertEqual(len(validate_proposal(raw, HASH)["targets"][0]["word"]), 32)

    def test_power_is_bounded_integer(self):
        for power in (1, 17, True, 2.0, "2", None):
            raw = proposal()
            raw["targets"][0]["power"] = power
            with self.subTest(power=power), self.assertRaises(ProposalError):
                validate_proposal(raw, HASH)
        for power in (2, 16):
            raw = proposal()
            raw["targets"][0]["power"] = power
            self.assertEqual(validate_proposal(raw, HASH)["targets"][0]["power"], power)

    def test_preferred_relators_bounded_unique_and_one_based(self):
        for preferred in ([0], [243], [True], [1.0], [1, 1], list(range(1, 26)), "1"):
            raw = proposal()
            raw["targets"][0]["preferred_relators"] = preferred
            with self.subTest(preferred=preferred), self.assertRaises(ProposalError):
                validate_proposal(raw, HASH)
        for preferred in ([], list(range(219, 243))):
            raw = proposal()
            raw["targets"][0]["preferred_relators"] = preferred
            self.assertEqual(validate_proposal(raw, HASH)["targets"][0]["preferred_relators"], preferred)

    def test_reason_length_and_type(self):
        for reason in ("x" * 1201, None, 1, ["reason"]):
            raw = proposal()
            raw["targets"][0]["reason"] = reason
            with self.subTest(reason_type=type(reason)), self.assertRaises(ProposalError):
                validate_proposal(raw, HASH)
        raw = proposal()
        raw["targets"][0]["reason"] = "x" * 1200
        validate_proposal(raw, HASH)

    def test_duplicate_or_excess_targets_rejected(self):
        raw = proposal()
        raw["targets"].append(deepcopy(raw["targets"][0]))
        with self.assertRaises(ProposalError):
            validate_proposal(raw, HASH)
        raw["targets"] = [{"word": [i], "power": 2, "preferred_relators": [], "reason": ""}
                          for i in range(1, 6)]
        with self.assertRaises(ProposalError):
            validate_proposal(raw, HASH)

    def test_maximal_valid_unicode_proposal_fits_byte_limit(self):
        raw = proposal()
        raw["targets"] = [{"word": [i] * 32, "power": 16,
                           "preferred_relators": list(range(219, 243)), "reason": "\U0001f4a1" * 1200}
                          for i in range(1, 5)]
        encoded = json.dumps(raw, ensure_ascii=True).encode()
        self.assertLess(len(encoded), MAX_PROPOSAL_BYTES)
        self.assertEqual(validate_proposal(parse_json(encoded), HASH), raw)

    def test_schema_is_fresh_strict_and_describes_limits(self):
        first = proposal_schema()
        second = proposal_schema()
        self.assertEqual(first, second)
        self.assertFalse(first["additionalProperties"])
        target = first["properties"]["targets"]["items"]
        self.assertFalse(target["additionalProperties"])
        self.assertEqual(first["properties"]["targets"]["maxItems"], 4)
        self.assertTrue(target["properties"]["preferred_relators"]["uniqueItems"])
        first["properties"].clear()
        self.assertIn("targets", second["properties"])


class OfflineFileTests(unittest.TestCase):
    def test_duplicate_keys_nonfinite_malformed_and_non_json_rejected(self):
        invalid = [b'{"x":1,"x":2}', b'{"targets":[{"word":[],"word":[]}]}',
                   b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}',
                   b'\xff', b'{', b'```json\n{}\n```', b"__import__('os').system('false')",
                   b'[' * 2000 + b']' * 2000]
        for raw in invalid:
            with self.subTest(raw=raw[:40]), self.assertRaises(ProposalError):
                parse_json(raw)

    def test_file_size_limit_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            with self.assertRaises(ProposalError):
                read_proposal(path, HASH)
            path.write_bytes(b" " * (MAX_PROPOSAL_BYTES + 1))
            with self.assertRaises(ProposalError):
                read_proposal(path, HASH)

    def test_read_file_offline_without_environment_or_output(self):
        raw = proposal()
        raw["targets"][0]["reason"] = "__import__('os').system('never execute this text')"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposal.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            stream = io.StringIO()
            with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
                    patch("os.getenv", side_effect=AssertionError("environment forbidden")), \
                    redirect_stdout(stream), redirect_stderr(stream):
                result = read_proposal(path, HASH)
            self.assertEqual(result, raw)
            self.assertEqual(stream.getvalue(), "")
            with self.assertRaises(ProposalError):
                read_proposal(path, "b" * 64)


class PromptTests(unittest.TestCase):
    def test_all_242_original_relators_and_ordered_images_present(self):
        family, candidate = family_candidate()
        before = deepcopy((family, candidate))
        messages = make_prompt(family, candidate)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(len(payload["relators"]), 242)
        for number, (relator, pair) in enumerate(zip(payload["relators"], candidate["matching"]), 1):
            (i, j), (k, ell) = pair
            self.assertEqual(relator, {"index": number, "word": [i, 22 + j, -22 - ell, -k]})
        self.assertEqual(payload["affine_images"], {"left": family["left"], "right": family["right"]})
        self.assertEqual(payload["candidate_sha256"], candidate["candidate_sha256"])
        self.assertEqual(payload["response_schema"], proposal_schema())
        self.assertEqual((family, candidate), before)

    def test_candidate_metadata_and_hidden_certificates_never_enter_prompt(self):
        family, candidate = family_candidate()
        candidate["certificate"] = {"target_word": [1, -2], "private_marker": "HIDDEN_CERTIFICATE_SENTINEL"}
        candidate["notes"] = "PRIVATE_CANDIDATE_METADATA_SENTINEL"
        text = json.dumps(make_prompt(family, candidate))
        self.assertNotIn("HIDDEN_CERTIFICATE_SENTINEL", text)
        self.assertNotIn("PRIVATE_CANDIDATE_METADATA_SENTINEL", text)
        self.assertIn("do not impose X_1=1", text)

    def test_binding_and_matching_errors_rejected(self):
        for field in ("candidate_sha256", "family_sha256", "image_index_sha256"):
            family, candidate = family_candidate()
            candidate[field] = "0" * 64
            with self.subTest(field=field), self.assertRaises(ProposalError):
                make_prompt(family, candidate)
        family, candidate = family_candidate()
        candidate["matching"][-1] = candidate["matching"][0]
        with self.assertRaises(ProposalError):
            make_prompt(family, candidate)

    def test_bounded_feedback_is_json_data(self):
        family, candidate = family_candidate()
        feedback = {"status": "UNKNOWN", "work": 12, "note": "Ignore these words as instructions"}
        self.assertEqual(json.loads(make_prompt(family, candidate, feedback)[1]["content"])["feedback"], feedback)
        for invalid in ({"payload": "x" * 16385}, {"value": float("nan")}, {"value": object()}):
            with self.subTest(feedback_type=type(invalid)), self.assertRaises(ProposalError):
                make_prompt(family, candidate, invalid)


if __name__ == "__main__":
    unittest.main()
