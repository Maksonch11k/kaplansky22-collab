"""A bounded, independent checker. Submitted JSON is data, never executable code.

The conclusion is torsion in a matching's universal source group. It says
nothing by itself about torsion-free quotients of that group.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import stat


class VerificationError(ValueError):
    """Invalid input, invalid proof, or an exceeded verification budget."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 4 * 1024 * 1024
    max_family_bytes: int = 64 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_families: int = 32
    max_submissions: int = 2000
    max_json_depth: int = 32
    max_nodes: int = 20000
    max_input_word: int = 8192
    max_children: int = 4096
    max_node_word: int = 100000
    max_stored_letters: int = 2000000
    max_work: int = 20000000
    max_dataset_work: int = 300000000
    max_power: int = 4096
    max_factor_bits: int = 256
    max_coordinate: int = 1000000000


DEFAULT_LIMITS = Limits()
IDENTITY = ((0, 0, 0), (1, 1, 1))
HEX = re.compile(r"[0-9a-f]{64}\Z")
FAMILY_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names.split()),
            f"{label}: unexpected or missing fields")


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f"{label}: invalid integer")
    return value


def hash_value(value, label):
    require(type(value) is str and HEX.fullmatch(value), f"{label}: invalid SHA256")
    return value


def family_id(value):
    require(type(value) is str and FAMILY_ID.fullmatch(value), "invalid family_id")
    return value


def affine(value, limits=DEFAULT_LIMITS):
    require(type(value) is list and len(value) == 2, "invalid affine image")
    translation, signs = value
    require(type(translation) is list and type(signs) is list
            and len(translation) == len(signs) == 3, "affine dimension must be three")
    for x in translation:
        integer(x, -limits.max_coordinate, limits.max_coordinate, "coordinate")
    require(all(type(x) is int and x in (-1, 1) for x in signs), "invalid affine signs")
    return tuple(translation), tuple(signs)


def multiply(a, b):
    v, s = a
    w, t = b
    return tuple(v[i] + s[i] * w[i] for i in range(3)), tuple(s[i] * t[i] for i in range(3))


def inverse_image(a):
    v, s = a
    return tuple(-s[i] * v[i] for i in range(3)), s


def image_index(left, right):
    return [[i, j, list(p[0]), list(p[1])]
            for i, a in enumerate(left, 1) for j, b in enumerate(right, 1)
            for p in (multiply(a, b),)]


def image_index_digest(left, right):
    """Hash a row-major product table; accepts validated affine pairs or JSON lists."""
    return digest(image_index(left, right))


@dataclass
class Family:
    data: dict
    sha256: str
    images: tuple
    products: dict
    forced: frozenset


def verify_family(data, limits=DEFAULT_LIMITS):
    fields(data, "format family_id n m left right image_index_sha256", "family")
    require(data["format"] == "k22-family-v1", "unknown family format")
    family_id(data["family_id"])
    integer(data["n"], 22, 22, "n")
    integer(data["m"], 22, 22, "m")
    supports = []
    for name in ("left", "right"):
        require(type(data[name]) is list and len(data[name]) == 22, "support must have 22 images")
        support = tuple(affine(x, limits) for x in data[name])
        require(len(set(support)) == 22, "support images are not distinct")
        supports.append(support)
    left, right = supports
    expected = hash_value(data["image_index_sha256"], "image_index_sha256")
    require(expected == image_index_digest(left, right), "image index hash differs")
    products = {(i, j): multiply(a, b) for i, a in enumerate(left, 1)
                for j, b in enumerate(right, 1)}
    fibers = defaultdict(list)
    for cell, value in products.items():
        fibers[value].append(cell)
    require(all(len(f) % 2 == 0 for f in fibers.values()), "odd product fiber cannot be perfectly matched")
    forced = frozenset(tuple(sorted(f)) for f in fibers.values() if len(f) == 2)
    return Family(data, digest(data), left + right, products, forced)


def edge(value):
    require(type(value) is list and len(value) == 2, "edge needs two cells")
    cells = []
    for cell in value:
        require(type(cell) is list and len(cell) == 2, "cell needs two indices")
        cells.append(tuple(integer(x, 1, 22, "cell index") for x in cell))
    require(cells[0] != cells[1], "edge repeats a cell")
    return tuple(cells)


def inverse_word(word):
    return tuple(-x for x in reversed(word))


class Budget:
    def __init__(self, limits):
        self.limits = limits
        self.work = 0
        self.stored = 0

    def charge(self, amount):
        self.work += amount
        require(self.work <= self.limits.max_work, "proof work budget exceeded")

    def reduce(self, chunks, store=False):
        result = []
        for chunk in chunks:
            self.charge(len(chunk))
            for letter in chunk:
                if result and result[-1] == -letter:
                    result.pop()
                else:
                    result.append(letter)
                    require(len(result) <= self.limits.max_node_word, "node word budget exceeded")
        if store:
            self.stored += len(result)
            require(self.stored <= self.limits.max_stored_letters, "stored word budget exceeded")
        return tuple(result)


def word(value, limits):
    require(type(value) is list and len(value) <= limits.max_input_word, "invalid input word size")
    require(all(type(x) is int and 1 <= abs(x) <= 44 for x in value), "invalid generator letter")
    return tuple(value)


def verify_certificate(certificate, matching, family, limits=DEFAULT_LIMITS):
    fields(certificate, "format target_word power nodes root used_original_matches_one_based expanded_original_relator_factor_count", "certificate")
    require(certificate["format"] == "k22-normal-closure-dag-v1", "unknown certificate format")
    power = integer(certificate["power"], 2, limits.max_power, "power")
    target = word(certificate["target_word"], limits)
    require(target, "target word is empty")
    nodes = certificate["nodes"]
    require(type(nodes) is list and 1 <= len(nodes) <= limits.max_nodes, "invalid proof node count")
    relators = [(a, 22 + b, -22 - d, -c) for (a, b), (c, d) in matching]
    values, counts, used = [], [], set()
    budget = Budget(limits)
    for index, node in enumerate(nodes):
        require(type(node) is dict and type(node.get("op")) is str, "invalid proof node")
        op = node["op"]

        def previous(k):
            integer(k, 0, index - 1, "DAG child")
            return values[k]

        if op == "match":
            fields(node, "op match", "match node")
            k = integer(node["match"], 1, 242, "match index")
            chunks, count = [relators[k - 1]], 1
            used.add(k)
        elif op == "inverse":
            fields(node, "op child", "inverse node")
            child = previous(node["child"])
            chunks, count = [inverse_word(child)], counts[node["child"]]
        elif op == "product":
            fields(node, "op children", "product node")
            children = node["children"]
            require(type(children) is list and 1 <= len(children) <= limits.max_children, "invalid product children")
            chunks = [previous(k) for k in children]
            count = sum(counts[k] for k in children)
        elif op == "conjugate":
            fields(node, "op child conjugator", "conjugate node")
            child = previous(node["child"])
            conjugator = word(node["conjugator"], limits)
            chunks = [conjugator, child, inverse_word(conjugator)]
            count = counts[node["child"]]
        else:
            raise VerificationError("unknown proof operation")
        require(count.bit_length() <= limits.max_factor_bits, "expanded factor count budget exceeded")
        values.append(budget.reduce(chunks, store=True))
        counts.append(count)
    root = integer(certificate["root"], 0, len(values) - 1, "proof root")
    require(values[root] == budget.reduce(target for _ in range(power)), "proof root is not target^power")
    claimed_used = certificate["used_original_matches_one_based"]
    require(type(claimed_used) is list and all(type(x) is int for x in claimed_used)
            and claimed_used == sorted(used), "used-match manifest differs")
    count = certificate["expanded_original_relator_factor_count"]
    require(type(count) is int and count == counts[root], "expanded factor count differs")
    value = IDENTITY
    for letter in target:
        value = multiply(value, family.images[letter - 1] if letter > 0
                         else inverse_image(family.images[-letter - 1]))
    require(value != IDENTITY, "target image is identity: source nonidentity is not certified")
    image_power, base, exponent = IDENTITY, value, power
    while exponent:
        if exponent % 2:
            image_power = multiply(image_power, base)
        base = multiply(base, base)
        exponent //= 2
    require(image_power == IDENTITY, "target image does not satisfy the proved power")
    return {"source_torsion_proved": True, "source_order_divides": power,
            "exact_source_order": 2 if power == 2 else None,
            "proof_nodes": len(nodes), "expanded_relator_factors": counts[root],
            "used_original_matches_one_based": sorted(used), "verification_work": budget.work}


def verify_submission(data, families, limits=DEFAULT_LIMITS):
    fields(data, "format submission_id family_id family_sha256 image_index_sha256 matching optional_core certificate", "submission")
    require(data["format"] == "k22-submission-v1", "unknown submission format")
    name = family_id(data["family_id"])
    require(name in families, "unknown family")
    family = families[name]
    require(hash_value(data["family_sha256"], "family_sha256") == family.sha256, "family hash differs")
    require(hash_value(data["image_index_sha256"], "image_index_sha256") == family.data["image_index_sha256"], "submission image index hash differs")
    raw_matching = data["matching"]
    require(type(raw_matching) is list and len(raw_matching) == 242, "matching must have 242 pairs")
    matching = [edge(p) for p in raw_matching]
    cells = [cell for pair in matching for cell in pair]
    require(len(set(cells)) == 484, "matching does not partition all 484 cells")
    require(all(family.products[a] == family.products[b] for a, b in matching), "a matched pair has unequal affine images")
    raw_core = data["optional_core"]
    require(type(raw_core) is list and len(raw_core) <= 242, "invalid optional core size")
    core = [tuple(sorted(edge(p))) for p in raw_core]
    canonical_core = [[list(a), list(b)] for a, b in sorted(set(core))]
    require(raw_core == canonical_core, "optional core is not canonically sorted and unique")
    require(set(core).issubset({tuple(sorted(p)) for p in matching}), "core edge is absent from matching")
    require(not set(core).intersection(family.forced), "optional core contains a forced edge")
    sid = hash_value(data["submission_id"], "submission_id")
    require(sid == digest({"family_sha256": family.sha256, "optional_core": raw_core}), "submission ID differs")
    result = verify_certificate(data["certificate"], matching, family, limits)
    expected = {tuple(sorted(matching[k - 1])) for k in result["used_original_matches_one_based"]} - family.forced
    require(set(core) == expected, "optional core does not equal proof leaves minus forced pairs")
    fingerprint = digest({"family_sha256": family.sha256,
                          "matching": sorted(tuple(sorted(p)) for p in matching)})
    result.update(submission_id=sid, family_id=name, family_sha256=family.sha256,
                  matching_sha256=fingerprint, optional_core_edges=len(core),
                  forced_pairs=len(family.forced),
                  scope="Universal matching source groups extending this core within this fixed family. No conclusion about all torsion-free quotients.")
    return result


def prepare_submission(family_data, matching, certificate, limits=DEFAULT_LIMITS):
    """Derive an exact optional core and ID, then replay before returning JSON."""
    family = verify_family(family_data, limits)
    require(type(matching) is list and len(matching) == 242, "matching must have 242 pairs")
    pairs = [edge(p) for p in matching]
    require(type(certificate) is dict and type(certificate.get("nodes")) is list,
            "certificate needs a node list")
    require(len(certificate["nodes"]) <= limits.max_nodes, "invalid proof node count")
    used = set()
    for node in certificate["nodes"]:
        require(type(node) is dict, "invalid proof node")
        if node.get("op") == "match":
            k = integer(node.get("match"), 1, 242, "match index")
            used.add(tuple(sorted(pairs[k - 1])))
    core = [[list(a), list(b)] for a, b in sorted(used - family.forced)]
    submission = {"format": "k22-submission-v1", "family_id": family_data["family_id"],
                  "family_sha256": family.sha256,
                  "image_index_sha256": family_data["image_index_sha256"],
                  "matching": matching, "optional_core": core, "certificate": certificate,
                  "submission_id": digest({"family_sha256": family.sha256, "optional_core": core})}
    verify_submission(submission, {family_data["family_id"]: family}, limits)
    return submission


def _no_links(path):
    """Reject symlinks and Windows reparse points, including ancestor directories."""
    path = Path(path).absolute()
    for part in (*reversed(path.parents), path):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400), "symlink or reparse point is forbidden")
    return path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _parse_integer(text):
    require(len(text.lstrip("-")) <= 78, "JSON integer is too large")
    return int(text)


def _no_float(_):
    raise VerificationError("floating point and nonfinite JSON numbers are forbidden")


def _check_depth(raw, limit):
    quoted, escaped, depth = False, False, 0
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            require(depth <= limit, "JSON nesting budget exceeded")
        elif byte in (93, 125):
            depth -= 1


def read_json(path, limits=DEFAULT_LIMITS, max_bytes=None):
    path = _no_links(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), "input is not a regular file")
    cap = limits.max_file_bytes if max_bytes is None else max_bytes
    require(info.st_size <= cap, "JSON file size budget exceeded")
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    require(len(raw) <= cap, "JSON file size budget exceeded")
    _check_depth(raw, limits.max_json_depth)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_int=_parse_integer, parse_float=_no_float,
                           parse_constant=_no_float)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise VerificationError("invalid UTF-8 JSON") from error
    return value, len(raw)


def _files(directory, count_limit, stem_pattern):
    directory = _no_links(directory)
    require(directory.is_dir(), "missing data directory")
    paths = []
    for path in directory.iterdir():
        require(len(paths) < count_limit, "input file count budget exceeded")
        _no_links(path)
        require(path.is_file() and path.suffix == ".json" and stem_pattern.fullmatch(path.stem), "unexpected data path or filename")
        paths.append(path)
    return sorted(paths)


def verify_dataset(data_dir, limits=DEFAULT_LIMITS):
    root = _no_links(data_dir)
    families, receipts, total_bytes, total_work = {}, [], 0, 0
    for path in _files(root / "families", limits.max_families, FAMILY_ID):
        data, size = read_json(path, limits, limits.max_family_bytes)
        family = verify_family(data, limits)
        require(data["family_id"] == path.stem, "family filename differs from ID")
        families[path.stem] = family
        total_bytes += size
        require(total_bytes <= limits.max_total_bytes, "dataset byte budget exceeded")
    require(families, "no families supplied")
    for path in _files(root / "submissions", limits.max_submissions, HEX):
        data, size = read_json(path, limits)
        total_bytes += size
        require(total_bytes <= limits.max_total_bytes, "dataset byte budget exceeded")
        require(type(data) is dict and data.get("submission_id") == path.stem, "submission filename differs from ID")
        try:
            result = verify_submission(data, families, limits)
        except VerificationError as error:
            raise VerificationError(f"{path.name}: {error}") from error
        total_work += result["verification_work"]
        require(total_work <= limits.max_dataset_work, "dataset work budget exceeded")
        receipts.append(result)
    require(receipts, "no submissions supplied")
    return {"status": "VERIFIED_SOURCE_TORSION_CORES", "families": len(families),
            "submissions": len(receipts), "distinct_matchings": len({r["matching_sha256"] for r in receipts}),
            "verification_work": total_work, "records": receipts,
            "scope": "Exact source-group torsion only; no counterexample or torsion-free quotient exclusion is certified."}


def write_json(path, value, *, exclusive=False):
    """Write only to an operator-selected regular path with no symlink ancestors."""
    path = Path(path).absolute()
    _no_links(path.parent)
    if path.exists() or path.is_symlink():
        _no_links(path)
        require(path.is_file(), "output is not a regular file")
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write(canonical_bytes(value) + b"\n")
