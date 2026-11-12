#!/usr/bin/env python3
"""Import public seed proofs from the read-only historical research workspace.

This importer copies mathematical data only. It does not import or execute
historical Python code, and it does not replace independent proof replay.
Run the repository verifier after import. New contributors submit inline
JSON directly and do not need the historical research workspace.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_bytes())


def within(base, relative):
    """Historical manifests may reference only files inside their input root."""
    path = (base / relative).resolve()
    require(path.is_relative_to(base.resolve()), "legacy reference escapes its input root")
    return path


def multiply(left, right):
    return [
        [left[0][i] + left[1][i] * right[0][i] for i in range(3)],
        [left[1][i] * right[1][i] for i in range(3)],
    ]


def canonical_edge(edge):
    require(isinstance(edge, list) and len(edge) == 2, "invalid edge")
    require(all(isinstance(cell, list) and len(cell) == 2 for cell in edge), "invalid cell")
    require(all(type(x) is int and 1 <= x <= 22 for cell in edge for x in cell), "invalid cell index")
    return tuple(sorted(tuple(cell) for cell in edge))


def make_family(family_id, left, right):
    require(len(left) == len(right) == 22, "expected 22 by 22 supports")
    for affine in left + right:
        require(isinstance(affine, list) and len(affine) == 2, "invalid affine image")
        require(all(isinstance(v, list) and len(v) == 3 for v in affine), "invalid affine dimensions")
        require(all(type(x) is int for v in affine for x in v), "noninteger affine image")
        require(all(x in (-1, 1) for x in affine[1]), "invalid diagonal signs")
    rows = []
    fibers = collections.defaultdict(list)
    for i, a in enumerate(left, 1):
        for j, b in enumerate(right, 1):
            translation, signs = multiply(a, b)
            rows.append([i, j, translation, signs])
            fibers[(tuple(translation), tuple(signs))].append((i, j))
    require(all(len(fiber) % 2 == 0 for fiber in fibers.values()), "odd product fiber")
    forced = frozenset(tuple(sorted(fiber)) for fiber in fibers.values() if len(fiber) == 2)
    family = {
        "format": "k22-family-v1",
        "family_id": family_id,
        "n": 22,
        "m": 22,
        "left": left,
        "right": right,
        "image_index_sha256": digest(rows),
    }
    return family, forced


def checked_submission(family, forced, source_path, proof_path, expected_edges):
    source = load(source_path)
    proof = load(proof_path)
    require(source["left"] == family["left"] and source["right"] == family["right"], "ordered support mismatch")
    require(proof["source_sha256"] == file_digest(source_path), "legacy proof source hash mismatch")
    require(source["diagram"]["n"] == source["diagram"]["m"] == proof["n"] == proof["m"] == 22, "dimension mismatch")
    require(proof["format"] == "original-matching-normal-closure-dag-v1", "unexpected legacy proof format")
    matching = source["diagram"]["matches"]
    require(len(matching) == 242, "incomplete matching")
    cells = []
    for edge in matching:
        canonical_edge(edge)
        (i, j), (k, ell) = edge
        require(multiply(family["left"][i - 1], family["right"][j - 1]) == multiply(family["left"][k - 1], family["right"][ell - 1]), "matching violates affine product equality")
        cells.extend(map(tuple, edge))
    require(len(set(cells)) == 484, "matching repeats cells")
    used = sorted({node["match"] for node in proof["nodes"] if node["op"] == "match"})
    require(used == proof["used_original_matches_one_based"], "legacy used-match manifest mismatch")
    require(all(type(index) is int and 1 <= index <= len(matching) for index in used), "invalid proof match index")
    core = frozenset(canonical_edge(matching[index - 1]) for index in used) - forced
    require(core == frozenset(map(canonical_edge, expected_edges)), "legacy core differs from its actual proof")
    require(core, "empty optional core requires separate universal-exclusion handling")
    optional_core = [[list(cell) for cell in edge] for edge in sorted(core)]
    certificate = {"format": "k22-normal-closure-dag-v1"}
    for name in (
        "target_word", "power", "nodes", "root",
        "used_original_matches_one_based", "expanded_original_relator_factor_count",
    ):
        certificate[name] = proof[name]
    # DAG nodes contain only the operation's mathematical fields.
    node_keys = {
        "match": {"op", "match"},
        "inverse": {"op", "child"},
        "product": {"op", "children"},
        "conjugate": {"op", "conjugator", "child"},
    }
    for node in certificate["nodes"]:
        require(node.get("op") in node_keys and set(node) == node_keys[node["op"]], "unexpected DAG node fields")
    family_sha256 = digest(family)
    submission_id = digest({"family_sha256": family_sha256, "optional_core": optional_core})
    submission = {
        "format": "k22-submission-v1",
        "submission_id": submission_id,
        "family_id": family["family_id"],
        "family_sha256": family_sha256,
        "image_index_sha256": family["image_index_sha256"],
        "matching": matching,
        "optional_core": optional_core,
        "certificate": certificate,
    }
    return submission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="Historical research workspace; read-only input")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--check", action="store_true", help="Reconstruct and compare exact output bytes without writing")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    parallel_root = workspace / "research_20261106_round3/mlsat/portable_235_core22_atlas"
    parallel_manifest = parallel_root / "atlas.json"
    trinomial_manifest = workspace / "research_20261106_round3/cem/final_allproofs_atlas.json"
    parallel = load(parallel_manifest)
    trinomial = load(trinomial_manifest)
    base = load(within(parallel_root, parallel["base_source"]))
    parallel_entries = [
        (within(parallel_root, item["directory"]) / "source.json", within(parallel_root, item["directory"]) / "torsion_certificate.json", item["edges"], i)
        for i, item in enumerate(parallel["cores"])
    ]
    trinomial_entries = []
    for i, item in enumerate(trinomial["cores"]):
        reference = trinomial["proof_manifest"][item["proof_index"]]
        source = within(workspace, reference["source"])
        proof = within(workspace, reference["certificate"])
        require(file_digest(source) == reference["source_sha256"], "trinomial source manifest hash mismatch")
        require(file_digest(proof) == reference["certificate_sha256"], "trinomial proof manifest hash mismatch")
        trinomial_entries.append((source, proof, item["edges"], i))
    collections_to_import = [
        ("parallel22", base["left"], base["right"], parallel_entries, parallel_manifest, 235, "parallel22-round3-235"),
        ("trinomial22", trinomial["left"], trinomial["right"], trinomial_entries, trinomial_manifest, 297, "trinomial22-round3-297"),
    ]
    outputs = {}
    provenance = []
    manifest = {"format": "k22-seed-manifest-v1", "families": [], "total_submissions": 0}
    for family_id, left, right, entries, legacy_manifest, expected_count, collection_id in collections_to_import:
        require(len(entries) == expected_count, "unexpected seed core count")
        family, forced = make_family(family_id, left, right)
        outputs[f"families/{family_id}.json"] = family
        ids = []
        power_bounds = collections.Counter()
        cores = []
        legacy_manifest_sha256 = file_digest(legacy_manifest)
        for source, proof, expected_edges, legacy_index in entries:
            submission = checked_submission(family, forced, source, proof, expected_edges)
            submission_id = submission["submission_id"]
            relative_path = f"submissions/{submission_id}.json"
            require(relative_path not in outputs, "duplicate seed core")
            outputs[relative_path] = submission
            ids.append(submission_id)
            power_bounds[submission["certificate"]["power"]] += 1
            cores.append(frozenset(map(canonical_edge, submission["optional_core"])))
            provenance.append({
                "submission_id": submission_id,
                "family_id": family_id,
                "seed_collection": collection_id,
                "legacy_core_index_zero_based": legacy_index,
                "legacy_manifest_sha256": legacy_manifest_sha256,
                "legacy_source_sha256": file_digest(source),
                "legacy_certificate_sha256": file_digest(proof),
            })
        require(not any(a <= b for i, a in enumerate(cores) for j, b in enumerate(cores) if i != j), "seed atlas contains redundant cores")
        manifest["families"].append({
            "family_id": family_id,
            "family_sha256": digest(family),
            "image_index_sha256": family["image_index_sha256"],
            "submission_count": len(ids),
            "submission_ids": sorted(ids),
            "power_bound_histogram": {str(k): v for k, v in sorted(power_bounds.items())},
        })
        manifest["total_submissions"] += len(ids)
    outputs["seed_manifest.json"] = manifest
    outputs["provenance.json"] = {"format": "k22-seed-provenance-v1", "records": sorted(provenance, key=lambda item: item["submission_id"])}
    byte_count = 0
    for relative_path, value in sorted(outputs.items()):
        content = canonical_bytes(value) + b"\n"
        # Only positive mathematical/provenance whitelists above enter output.
        # This additional scan prevents accidentally publishing old paths.
        lower = content.lower()
        require(not any(token in lower for token in (b"c:/users/", b"c:\\\\users\\\\", b"/kaggle/", b"api_key", b"access_token")), "private path or secret-like field in output")
        target = args.output / relative_path
        if args.check:
            require(target.is_file() and target.read_bytes() == content, "output differs: " + relative_path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        byte_count += len(content)
    print(json.dumps({
        "status": "IMPORT_REPRODUCED" if args.check else "IMPORTED_REPLAY_REQUIRED",
        "submissions": manifest["total_submissions"],
        "files": len(outputs), "bytes": byte_count,
        "families": [{k: v for k, v in item.items() if k != "submission_ids"} for item in manifest["families"]],
    }, indent=2))


if __name__ == "__main__":
    main()
