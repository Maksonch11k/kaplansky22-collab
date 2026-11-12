"""Public-data helpers shared by search models. Standard library only.

No historical workspace helpers, model pickles, credentials, or proof-search
engine are needed. Loading a problem first replays the public proof atlas.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re

Cell = tuple[int, int]
Edge = tuple[Cell, Cell]


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def edge_key(edge) -> Edge:
    return tuple(sorted(tuple(cell) for cell in edge))


def affine_product(left, right):
    t, s = left
    u, r = right
    return (tuple(t[k] + s[k] * u[k] for k in range(3)),
            tuple(s[k] * r[k] for k in range(3)))


def product_fibers(family: dict) -> tuple[tuple[Cell, ...], ...]:
    groups = defaultdict(list)
    for i, left in enumerate(family["left"], 1):
        for j, right in enumerate(family["right"], 1):
            groups[affine_product(left, right)].append((i, j))
    return tuple(tuple(sorted(cells)) for _, cells in sorted(groups.items()))


@dataclass
class Problem:
    family: dict
    submissions: list[dict]

    def __post_init__(self):
        self.family_sha256 = fingerprint(self.family)
        self.fibers = product_fibers(self.family)
        if any(len(f) % 2 for f in self.fibers):
            raise ValueError("An odd product fiber has no perfect matching")
        self.optional_fibers = tuple(f for f in self.fibers if len(f) > 2)
        self.edges = tuple(sorted(edge_key(e) for f in self.fibers
                                  for e in combinations(f, 2)))
        self.edge_ids = {e: i for i, e in enumerate(self.edges)}
        self.forced_bits = self.encode(edge_key(f) for f in self.fibers if len(f) == 2)
        self.cores = tuple(self.encode(s["optional_core"]) for s in self.submissions)
        self.references = tuple(sorted({self.encode(s["matching"]) & ~self.forced_bits
                                        for s in self.submissions}))
        self.optional_edge_count = self.family["n"] * self.family["m"] // 2 - self.forced_bits.bit_count()

    def encode(self, edges) -> int:
        bits = 0
        for edge in edges:
            bits |= 1 << self.edge_ids[edge_key(edge)]
        return bits

    def decode(self, bits: int) -> list:
        result = []
        while bits:
            bit = bits & -bits
            result.append(self.edges[bit.bit_length() - 1])
            bits ^= bit
        return result

    def score(self, bits: int) -> dict:
        optional = bits & ~self.forced_bits
        missing = [(core & ~optional).bit_count() for core in self.cores]
        violations = sum(count == 0 for count in missing)
        pressure = sum(2.0 ** (-min(count, 16)) for count in missing)
        novelty = 1 - max(((optional & ref).bit_count() for ref in self.references), default=0) / max(1, self.optional_edge_count)
        return {"score": -1000 * violations - pressure + .05 * novelty,
                "known_core_violations": violations, "core_pressure": pressure,
                "novelty": novelty}

    def candidate(self, bits: int) -> dict:
        matching = self.decode(bits)
        return {"format": "k22-candidate-v1", "family_id": self.family["family_id"],
                "family_sha256": self.family_sha256,
                "image_index_sha256": self.family["image_index_sha256"],
                "matching": matching,
                "candidate_sha256": fingerprint({"family_sha256": self.family_sha256,
                                                   "matching": matching}),
                "status": "UNPROVED_CANDIDATE"}


def load_problem(data: Path, family_id: str, report: Path | None = None) -> Problem:
    """Replay all submissions, then load one immutable ordered family.

    The public verifier is deliberately the trust boundary. Model code does not
    implement or replace proof verification. Run from the repository root.
    """
    from k22.verifier import read_json, verify_dataset, verify_family, verify_submission

    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", family_id):
        raise ValueError("family_id must be a simple file stem")
    receipt = verify_dataset(data)
    family, _ = read_json(data / "families" / f"{family_id}.json")
    checked_family = verify_family(family)
    submissions = []
    for path in sorted((data / "submissions").glob("*.json")):
        submission, _ = read_json(path)
        if submission["family_id"] == family_id:
            # Check the exact in-memory objects used below, even if a data file
            # changed after the dataset-level resource and naming checks.
            verify_submission(submission, {family_id: checked_family})
            submissions.append(submission)
    if report is not None:
        write_json(report, receipt)
    return Problem(family, submissions)


def write_json(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
