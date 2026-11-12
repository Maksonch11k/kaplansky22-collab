"""Bounded original-relator proof search for untrusted proposed torsion words.

This producer never reads a proof atlas. It retains cyclic relators, derives
new ones from common prefixes of their rotations/inverses, and tries strictly
shortening Dehn rewrites of the requested powers. Every successful rewrite is
exported as a normal-closure DAG over the original 242 matching relators.
The unchanged public verifier must accept the result before success is returned.

``max_rules`` bounds retained cyclic relators; rotations are generated lazily.
``max_operations`` counts comparisons, index insertions, and rewrite attempts.
The time limit covers search; validation/replay time is reported separately.
Failure at a bound, or saturation of this incomplete procedure, means UNKNOWN.
"""

from __future__ import annotations

from collections import defaultdict, deque
import math
import time

from k22.verifier import (IDENTITY, VerificationError, edge, inverse_image,
                          multiply, prepare_submission, verify_family)


MAX_WORD = 64
MAX_NODES = 18000
MAX_TARGETS = 32


def _require(test, message):
    if not test:
        raise ValueError(message)


def _inverse(word):
    return tuple(-letter for letter in reversed(word))


def _reduce(word):
    result = []
    for letter in word:
        if result and result[-1] == -letter:
            result.pop()
        else:
            result.append(letter)
    return tuple(result)


def _canonical(word):
    """Return a cyclic representative and explicit conjugation/inversion data."""
    reduced = _reduce(word)
    cut = 0
    while 2 * cut < len(reduced) and reduced[cut] == -reduced[-1 - cut]:
        cut += 1
    prefix = reduced[:cut]
    cyclic = reduced[cut:len(reduced) - cut] if cut else reduced
    if not cyclic:
        return (), prefix, False, ()
    variants = []
    for flipped, base in ((False, cyclic), (True, _inverse(cyclic))):
        for start in range(len(base)):
            variants.append((base[start:] + base[:start], flipped, base[:start]))
    chosen, flipped, rotation_prefix = min(variants)
    return chosen, prefix, flipped, rotation_prefix


class _Stop(Exception):
    pass


class _Budget:
    def __init__(self, operations, rules, seconds):
        self.max_operations = operations
        self.max_rules = rules
        self.operations = 0
        self.start = time.monotonic()
        self.deadline = self.start + seconds

    def tick(self):
        if time.monotonic() >= self.deadline:
            raise _Stop("max_seconds")
        if self.operations >= self.max_operations:
            raise _Stop("max_operations")
        self.operations += 1


class _Log:
    """Proof constructors only; no theorem is inferred from a failed search."""

    def __init__(self):
        self.nodes = []
        self.counts = []

    def add(self, node, count):
        if len(self.nodes) >= MAX_NODES:
            raise _Stop("proof_node_limit")
        if count.bit_length() > 250:
            raise _Stop("proof_factor_limit")
        self.nodes.append(node)
        self.counts.append(count)
        return len(self.nodes) - 1

    def match(self, index):
        return self.add({"op": "match", "match": index}, 1)

    def inverse(self, child):
        if self.nodes[child]["op"] == "inverse":
            return self.nodes[child]["child"]
        return self.add({"op": "inverse", "child": child}, self.counts[child])

    def product(self, children):
        if len(children) == 1:
            return children[0]
        return self.add({"op": "product", "children": list(children)}, sum(self.counts[c] for c in children))

    def conjugate(self, child, conjugator):
        if not conjugator:
            return child
        return self.add({"op": "conjugate", "child": child,
                         "conjugator": list(conjugator)}, self.counts[child])

    def compact(self, root, target, power):
        reachable, pending = set(), [root]
        while pending:
            index = pending.pop()
            if index in reachable:
                continue
            reachable.add(index)
            node = self.nodes[index]
            if "child" in node:
                pending.append(node["child"])
            if "children" in node:
                pending.extend(node["children"])
        remap, nodes, used = {}, [], set()
        for old in sorted(reachable):
            node = dict(self.nodes[old])
            if "child" in node:
                node["child"] = remap[node["child"]]
            if "children" in node:
                node["children"] = [remap[c] for c in node["children"]]
            if node["op"] == "match":
                used.add(node["match"])
            remap[old] = len(nodes)
            nodes.append(node)
        return {"format": "k22-normal-closure-dag-v1", "target_word": list(target),
                "power": power, "nodes": nodes, "root": remap[root],
                "used_original_matches_one_based": sorted(used),
                "expanded_original_relator_factor_count": self.counts[root]}


def _validate_targets(targets):
    _require(type(targets) is list and len(targets) <= MAX_TARGETS,
             "targets must contain at most 32 proposals")
    normalized = []
    for target in targets:
        _require(type(target) is dict and set(target) == {"word", "power", "preferred_relators", "reason"},
                 "proposal fields must be word, power, preferred_relators, reason")
        word, power, preferred = target["word"], target["power"], target["preferred_relators"]
        _require(type(word) is list and 1 <= len(word) <= MAX_WORD
                 and all(type(x) is int and 1 <= abs(x) <= 44 for x in word), "invalid proposed word")
        _require(type(power) is int and 2 <= power <= 16, "power must be an integer in 2..16")
        _require(type(preferred) is list and len(preferred) <= 242
                 and all(type(x) is int and 1 <= x <= 242 for x in preferred)
                 and len(set(preferred)) == len(preferred), "invalid preferred relator indices")
        _require(type(target["reason"]) is str and len(target["reason"]) <= 2000,
                 "reason must be a string of at most 2000 characters")
        normalized.append((tuple(word), power, preferred))
    return normalized


class _Search:
    def __init__(self, relators, targets, budget):
        self.relators = relators
        self.targets = targets
        self.budget = budget
        self.log = _Log()
        self.known = {}
        self.pending = deque()
        self.orientations = defaultdict(list)
        self.prefixes = defaultdict(list)
        self.oriented_nodes = {}
        self.overlaps = 0
        self.derived = 0
        self.rewrites = 0

    def add_relation(self, raw, make_node, derived=False):
        self.budget.tick()
        if len(raw) > MAX_WORD:
            return
        canonical, prefix, flipped, rotation_prefix = _canonical(raw)
        if not canonical or canonical in self.known:
            return
        if len(self.known) >= self.budget.max_rules:
            raise _Stop("max_rules")
        node = make_node()
        node = self.log.conjugate(node, _inverse(prefix))
        if flipped:
            node = self.log.inverse(node)
        node = self.log.conjugate(node, _inverse(rotation_prefix))
        self.known[canonical] = node
        self.pending.append((canonical, node))
        self.derived += int(derived)

    def oriented_node(self, record):
        oriented, base_node, flipped, prefix = record
        key = (base_node, flipped, prefix)
        if key not in self.oriented_nodes:
            node = self.log.inverse(base_node) if flipped else base_node
            self.oriented_nodes[key] = self.log.conjugate(node, _inverse(prefix))
        return self.oriented_nodes[key]

    def reduce_target(self, target, power):
        current, steps = _reduce(target * power), []
        while current:
            replacement = None
            for start, first in enumerate(current):
                for record in self.orientations[first]:
                    # Even a rule too long to shorten this suffix consumes a
                    # bounded attempt; a large bucket must not bypass the clock.
                    self.budget.tick()
                    relation = record[0]
                    for length in range(min(len(relation), len(current) - start), len(relation) // 2, -1):
                        self.budget.tick()
                        if current[start:start + length] == relation[:length]:
                            replacement = (start, record, length)
                            break
                    if replacement:
                        break
                if replacement:
                    break
            if replacement is None:
                return None
            start, record, length = replacement
            prefix = current[:start]
            steps.append((prefix, record))
            current = _reduce(prefix + _inverse(record[0][length:]) + current[start + length:])
            self.rewrites += 1
        # At each step old * new^-1 = prefix * relation * prefix^-1.
        # Their product telescopes to the original target power.
        factors = [self.log.conjugate(self.oriented_node(record), prefix) for prefix, record in steps]
        return self.log.product(factors) if factors else None

    def run(self, preferred):
        order = list(dict.fromkeys(preferred + list(range(1, 243))))
        sources = iter(order)
        while True:
            self.budget.tick()
            if not self.pending:
                try:
                    index = next(sources)
                except StopIteration:
                    raise _Stop("saturated")
                self.add_relation(self.relators[index - 1], lambda index=index: self.log.match(index))
                continue
            relation, node = self.pending.popleft()
            oriented = []
            distinct = set()
            for flipped, base in ((False, relation), (True, _inverse(relation))):
                for rotation in range(len(base)):
                    self.budget.tick()
                    value = base[rotation:] + base[:rotation]
                    if value in distinct:
                        continue
                    distinct.add(value)
                    record = (value, node, flipped, base[:rotation])
                    oriented.append(record)
                    self.orientations[value[0]].append(record)
            for index, target, power in self.targets:
                root = self.reduce_target(target, power)
                if root is not None:
                    return index, self.log.compact(root, target, power)
            for record in oriented:
                value = record[0]
                # A shared prefix p in p*a and p*b gives a^-1*b as a
                # product of two proved relators. Include self-overlaps too.
                for length in range(2, min(8, len(value)) + 1):
                    self.budget.tick()
                    prefix = value[:length]
                    for other in self.prefixes[prefix]:
                        self.budget.tick()
                        if value == other[0]:
                            continue
                        self.overlaps += 1
                        consequence = _reduce(_inverse(other[0][length:]) + value[length:])

                        def make_node(other=other, record=record):
                            return self.log.product([self.log.inverse(self.oriented_node(other)),
                                                     self.oriented_node(record)])

                        self.add_relation(consequence, make_node, derived=True)
                    self.prefixes[prefix].append(record)


def search(family_data, matching, targets, *, max_operations=20000,
           max_rules=2000, max_seconds=10.0):
    """Search original matching relators, returning a replayed proof or UNKNOWN.

    Invalid inputs raise ValueError. An empty target list or limits of zero
    return UNKNOWN. Reasons are inert text; preferred indices affect order only.
    No anchors, extra relations, finite-quotient inference, or stored proofs are
    used. The method is incomplete and never certifies torsion-freeness.
    """
    started = time.monotonic()
    _require(type(max_operations) is int and 0 <= max_operations <= 200000, "max_operations must be in 0..200000")
    _require(type(max_rules) is int and 0 <= max_rules <= 5000, "max_rules must be in 0..5000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds)
             and 0 <= max_seconds <= 60, "max_seconds must be finite and in 0..60")
    proposals = _validate_targets(targets)
    family = verify_family(family_data)
    _require(type(matching) is list and len(matching) == 242, "expected 242 matching pairs")
    pairs = [edge(pair) for pair in matching]
    _require(len({cell for pair in pairs for cell in pair}) == 484, "matching must partition 484 cells")
    _require(all(family.products[a] == family.products[b] for a, b in pairs), "matching has unequal affine products")
    relators = [(i, 22 + j, -22 - l, -k) for (i, j), (k, l) in pairs]
    eligible, target_results, preferred = [], [], []
    for index, (word, power, indices) in enumerate(proposals):
        value = IDENTITY
        for letter in word:
            value = multiply(value, family.images[letter - 1] if letter > 0
                             else inverse_image(family.images[-letter - 1]))
        raised = IDENTITY
        for _ in range(power):
            raised = multiply(raised, value)
        status = "UNKNOWN"
        if value == IDENTITY:
            status = "SKIPPED_IDENTITY_IMAGE"
        elif raised != IDENTITY:
            status = "SKIPPED_POWER_IMAGE_MISMATCH"
        else:
            eligible.append((index, word, power))
            preferred.extend(indices)
        target_results.append({"target_index": index, "status": status})
    validation_seconds = time.monotonic() - started
    budget = _Budget(max_operations, max_rules, max_seconds)
    engine = _Search(relators, eligible, budget)
    certificate, target_index = None, None
    stop_reason = "no_eligible_targets"
    if eligible:
        try:
            target_index, certificate = engine.run(preferred)
            stop_reason = "proved_power"
        except _Stop as stop:
            stop_reason = str(stop)
    search_seconds = time.monotonic() - budget.start
    verification_seconds = 0.0
    optional_core, submission_id, verification_error = None, None, None
    if certificate is not None:
        replay_start = time.monotonic()
        try:
            prepared = prepare_submission(family_data, matching, certificate)
        except VerificationError as error:
            # A producer bug or a checker resource bound must never become success.
            verification_error = str(error)
            certificate = None
            stop_reason = "independent_verification_rejected"
        else:
            optional_core, submission_id = prepared["optional_core"], prepared["submission_id"]
            target_results[target_index]["status"] = "CERTIFIED_SOURCE_TORSION"
        verification_seconds = time.monotonic() - replay_start
    return {"status": "CERTIFIED_SOURCE_TORSION" if certificate else "UNKNOWN",
            "certificate": certificate, "target_index": target_index,
            "optional_core": optional_core, "submission_id": submission_id,
            "family_sha256": family.sha256, "stop_reason": stop_reason,
            "verification_error": verification_error,
            "target_results": target_results,
            "metrics": {"operations": budget.operations, "retained_rules": len(engine.known),
                        "derived_rules": engine.derived, "overlap_comparisons": engine.overlaps,
                        "dehn_rewrites": engine.rewrites, "allocated_proof_nodes": len(engine.log.nodes),
                        "exported_proof_nodes": len(certificate["nodes"]) if certificate else 0,
                        "validation_seconds": validation_seconds, "search_seconds": search_seconds,
                        "verification_seconds": verification_seconds,
                        "elapsed_seconds": time.monotonic() - started},
            "limits": {"max_operations": max_operations, "max_rules": max_rules,
                       "max_seconds": max_seconds, "max_relator_length": MAX_WORD,
                       "max_proof_nodes": MAX_NODES},
            "scope": "Source torsion only. UNKNOWN is not torsion-freeness; no claim about all torsion-free quotients."}
