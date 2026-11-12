"""Merge independently verified core datasets into a separate new dataset.

No source files are changed. A shared core ID keeps the base certificate;
additional IDs mean additional cores relative to this base, not global novelty.
"""
from __future__ import annotations

from pathlib import Path

from k22.verifier import (DEFAULT_LIMITS, VerificationError, canonical_bytes,
                         digest, read_json, verify_dataset, verify_family,
                         verify_submission)


def _require(condition, message):
    if not condition:
        raise VerificationError(message)


def _output_is_safe(output, inputs):
    for path in (output, *output.parents):
        _require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(),
                 "Output must not contain symlink or junction ancestors")
    resolved = output.resolve()
    for source in inputs:
        resolved_source = source.resolve()
        _require(not resolved.is_relative_to(resolved_source)
                 and not resolved_source.is_relative_to(resolved),
                 "Output must be separate from both input trees")
    _require(not output.exists() or output.is_dir() and not any(output.iterdir()),
             "Output must be a new or empty directory")


def _paths(directory, cap):
    paths = []
    for path in directory.iterdir():
        _require(len(paths) < cap, "Input file count budget exceeded")
        _require(path.suffix == ".json", "Unexpected dataset filename")
        paths.append(path)
    return sorted(paths)


def _snapshot(root):
    """Verify the dataset, then independently validate the exact loaded objects.

    The second pass ensures that a file changed after dataset verification is
    never merely copied on the strength of the earlier verification receipt.
    """
    limits = DEFAULT_LIMITS
    verify_dataset(root, limits)
    families, checked_families, submissions, work_by_id = {}, {}, {}, {}
    total_bytes = total_work = 0
    for path in _paths(root / "families", limits.max_families):
        value, size = read_json(path, limits, limits.max_family_bytes)
        checked = verify_family(value, limits)
        family_id = value["family_id"]
        _require(path.stem == family_id, "Family filename differs from checked ID")
        families[family_id], checked_families[family_id] = value, checked
        total_bytes += size
        _require(total_bytes <= limits.max_total_bytes, "Input byte budget exceeded")
    _require(families, "No families supplied")
    for path in _paths(root / "submissions", limits.max_submissions):
        value, size = read_json(path, limits)
        total_bytes += size
        _require(total_bytes <= limits.max_total_bytes, "Input byte budget exceeded")
        receipt = verify_submission(value, checked_families, limits)
        core_id = value["submission_id"]
        _require(path.stem == core_id, "Submission filename differs from checked ID")
        submissions[core_id] = value
        work_by_id[core_id] = receipt["verification_work"]
        total_work += receipt["verification_work"]
        _require(total_work <= limits.max_dataset_work, "Input verification work budget exceeded")
    _require(submissions, "No submissions supplied")
    return families, submissions, work_by_id


def merge_data(base: Path, feedback: Path, output: Path):
    """Verify both inputs, union exact core IDs, write and replay a fresh dataset."""
    base, feedback, output = (Path(path).absolute() for path in (base, feedback, output))
    _output_is_safe(output, (base, feedback))
    base_families, base_cores, base_work = _snapshot(base)
    feedback_families, feedback_cores, feedback_work = _snapshot(feedback)
    families = dict(base_families)
    for family_id, family in feedback_families.items():
        if family_id in families:
            _require(families[family_id] == family and digest(families[family_id]) == digest(family),
                     "Same family ID has different ordered images or fingerprints")
        else:
            families[family_id] = family
    duplicates = set(base_cores) & set(feedback_cores)
    for core_id in duplicates:
        first, second = base_cores[core_id], feedback_cores[core_id]
        _require(first["family_sha256"] == second["family_sha256"]
                 and first["optional_core"] == second["optional_core"], "Conflicting core ID")
    cores = dict(feedback_cores)
    cores.update(base_cores)  # Explicitly retain the base proof for duplicate IDs.
    work = dict(feedback_work)
    work.update(base_work)
    limits = DEFAULT_LIMITS
    _require(len(families) <= limits.max_families, "Merged family count budget exceeded")
    _require(len(cores) <= limits.max_submissions, "Merged submission count budget exceeded")
    _require(sum(work.values()) <= limits.max_dataset_work, "Merged verification work budget exceeded")
    encoded, total_bytes = [], 0
    for folder, values, cap in (("families", families, limits.max_family_bytes),
                                ("submissions", cores, limits.max_file_bytes)):
        for checked_id, value in sorted(values.items()):
            raw = canonical_bytes(value) + b"\n"
            _require(len(raw) <= cap, "Merged file byte budget exceeded")
            total_bytes += len(raw)
            _require(total_bytes <= limits.max_total_bytes, "Merged dataset byte budget exceeded")
            encoded.append((folder, checked_id, raw))
    # Every input object, union conflict and output resource bound is checked
    # before creating anything. A late filesystem error leaves inputs intact.
    _output_is_safe(output, (base, feedback))
    output.mkdir(parents=True, exist_ok=True)
    (output / "families").mkdir()
    (output / "submissions").mkdir()
    for folder, checked_id, raw in encoded:
        with (output / folder / f"{checked_id}.json").open("xb") as stream:
            stream.write(raw)
    receipt = verify_dataset(output, limits)
    _require(receipt["families"] == len(families) and receipt["submissions"] == len(cores),
             "Merged dataset changed during verification")
    return {
        "format": "k22-data-merge-v1", "status": "MERGED_AND_VERIFIED",
        "base_families": len(base_families), "feedback_families": len(feedback_families),
        "added_families": len(set(feedback_families) - set(base_families)),
        "merged_families": len(families),
        "base_cores": len(base_cores), "feedback_cores": len(feedback_cores),
        "added_cores_relative_to_base": len(set(feedback_cores) - set(base_cores)),
        "duplicate_core_ids": len(duplicates), "merged_cores": len(cores),
        "merged_bytes": total_bytes, "verification_work": receipt["verification_work"],
        "scope": "Verified source-torsion cores; additional IDs are relative to the supplied base only. No global novelty, torsion-free group, or quotient exclusion is claimed.",
    }
