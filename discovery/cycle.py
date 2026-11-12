"""Persistent local handoff: candidate -> chat hypothesis -> proof -> feedback.

This module never contacts a model or executes model-generated code. The agent
in the user's existing chat reads prompt.json and writes a bounded proposal.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import time

from k22.verifier import (VerificationError, canonical_bytes, digest, edge,
    prepare_submission, read_json, verify_dataset, verify_family, verify_submission)
from models.common import Problem, load_problem
from models.cem import Policy
from .proposals import make_prompt, parse_json, read_proposal
from .proof_search import search

STATE_FORMAT = "k22-chat-cycle-v1"
DEMO_CORE = "3790f085a9b33d1bc998777a9c18c044b73bc2faafe639bd5a9017a5b60d51db"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write(path: Path, value):
    """Replace one operator-owned output atomically; no path comes from a model."""
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), "Output must not be a symlink")
    temporary = path.with_name(path.name + ".tmp")
    require(not temporary.is_symlink(), "Temporary output must not be a symlink")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, path)


def _state_hash(value, label):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), f"Invalid {label}")


def _state_integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f"Invalid {label}")


def _state_core(submission):
    return frozenset(tuple(sorted(map(tuple, item))) for item in submission["optional_core"])


def _read_cycle_json(path, max_bytes=1024 * 1024):
    """Bound reads before parsing; unlike certificates, logs contain timings."""
    require(not path.is_symlink() and path.is_file(), "Run artifact must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    return parse_json(raw, max_bytes=max_bytes)


def _replay_state_history(run_dir, state):
    """Derive mathematical outcomes and admission counters from actual proofs."""
    config = state["config"]
    problem = load_problem(Path(state["base_data"]), config["family_id"])
    require(problem.family_sha256 == state["family_sha256"] and atlas_hash(problem) == state["base_atlas_sha256"],
            "Base inputs changed; start a new run")
    saved_family, _ = read_json(run_dir / "family.json")
    require(saved_family == problem.family, "Saved run family changed")
    checked_family = verify_family(problem.family)
    omitted = state["demo_omitted_seed_core"]
    require(omitted is None or any(s["submission_id"] == omitted for s in problem.submissions), "Missing demo reference core")
    memory = {s["submission_id"]: s for s in problem.submissions if s["submission_id"] != omitted}
    feedback = run_dir / "verified"
    # An interrupted advance may leave a valid, uncommitted proof on disk.
    # Check every file but admit only proofs committed in chronological history.
    if (feedback / "submissions").exists() and any((feedback / "submissions").glob("*.json")):
        verify_dataset(feedback)
    candidates = {}
    common_fields = {"round", "candidate_sha256", "proposal_sha256", "status", "added_to_memory",
                     "seconds", "core_count_before", "core_count_after"}
    proof_fields = {"submission_id", "power_divides", "optional_core_edges", "novelty"}
    for index, record in enumerate(state["history"], 1):
        require(type(record) is dict, "Invalid history record")
        status = record.get("status")
        require(status in ("CERTIFIED_SOURCE_TORSION", "UNKNOWN"), "Invalid history status")
        require(set(record) == common_fields | (proof_fields if status == "CERTIFIED_SOURCE_TORSION" else set()),
                "Unexpected history fields or unsupported proof claim")
        _state_integer(record["round"], index, index, "history round sequence")
        for field in ("candidate_sha256", "proposal_sha256"):
            _state_hash(record[field], field)
        require(type(record["added_to_memory"]) is bool, "Admission flag must be boolean")
        require(type(record["seconds"]) in (int, float) and math.isfinite(record["seconds"])
                and record["seconds"] >= 0, "Invalid history duration")
        _state_integer(record["core_count_before"], len(memory), len(memory), "core_count_before")
        directory = run_dir / f"round_{index:03d}"
        candidate, _ = read_json(directory / "candidate.json")
        validate_candidate(candidate, problem.family)
        require(candidate["candidate_sha256"] == record["candidate_sha256"], "History candidate hash differs")
        candidates[index] = candidate
        proposal = read_proposal(directory / "accepted_proposal.json", candidate["candidate_sha256"])
        require(digest(proposal) == record["proposal_sha256"], "History proposal hash differs")
        result = _read_cycle_json(directory / "search.json", max_bytes=4 * 1024 * 1024)
        require(type(result) is dict and result.get("status") == status, "History status differs from saved search")
        if status == "UNKNOWN":
            require(record["added_to_memory"] is False and result.get("certificate") is None
                    and result.get("optional_core") is None and result.get("submission_id") is None,
                    "UNKNOWN cannot claim a proof or memory admission")
        else:
            _state_hash(record["submission_id"], "submission_id")
            submission, _ = read_json(directory / "submission.json")
            checked = verify_submission(submission, {config["family_id"]: checked_family})
            require(submission["matching"] == candidate["matching"], "History proof matching differs from its candidate")
            require(submission["submission_id"] == record["submission_id"], "History proof ID differs")
            require(result.get("certificate") == submission["certificate"], "Saved search certificate differs")
            require(result.get("submission_id", submission["submission_id"]) == submission["submission_id"]
                    and result.get("optional_core", submission["optional_core"]) == submission["optional_core"],
                    "Saved search proof metadata differs")
            core = _state_core(submission)
            _state_integer(record["power_divides"], checked["source_order_divides"], checked["source_order_divides"], "power bound")
            _state_integer(record["optional_core_edges"], len(core), len(core), "optional core size")
            same = submission["submission_id"] in memory
            redundant = any(_state_core(old) <= core for old in memory.values())
            novelty = "KNOWN_CORE" if same else "REDUNDANT_CORE" if redundant else "NEW_TO_RUN_MEMORY"
            require(record["novelty"] == novelty, "History novelty claim differs from verified inputs")
            require(record["added_to_memory"] is (not redundant), "History admission claim differs")
            if not redundant:
                path = feedback / "submissions" / f"{submission['submission_id']}.json"
                admitted, _ = read_json(path)
                verify_submission(admitted, {config["family_id"]: checked_family})
                require(admitted == submission, "Committed feedback differs from the round proof")
                memory[submission["submission_id"]] = submission
        _state_integer(record["core_count_after"], len(memory), len(memory), "core_count_after")
    if state["status"] in ("AWAITING_PROPOSAL", "COMPLETED"):
        index = state["round_index"]
        candidate = candidates.get(index)
        if candidate is None:
            candidate, _ = read_json(run_dir / f"round_{index:03d}" / "candidate.json")
            validate_candidate(candidate, problem.family)
        require(state["current_candidate_sha256"] == candidate["candidate_sha256"], "Current candidate hash differs")
        require(state["current_candidate_file_sha256"] == digest(candidate), "Saved candidate changed")
    elif "current_candidate_sha256" in state:
        require(candidates, "Unexpected stale candidate binding")
        previous = candidates[len(state["history"])]
        require(state["current_candidate_sha256"] == previous["candidate_sha256"]
                and state["current_candidate_file_sha256"] == digest(previous), "Stale candidate binding differs")


def read_state(run_dir: Path):
    run_dir = Path(run_dir)
    state = _read_cycle_json(run_dir / "state.json")
    required = {"format", "status", "config", "base_data", "family_sha256", "base_atlas_sha256",
                "code_revision", "round_index", "history", "demo", "demo_omitted_seed_core"}
    optional = {"current_candidate_sha256", "current_candidate_file_sha256", "stop_reason"}
    require(type(state) is dict and required <= set(state) <= required | optional, "Unexpected run state fields")
    require(state["format"] == STATE_FORMAT, "Unsupported run state")
    config = state["config"]
    require(type(config) is dict and set(config) == {"family_id", "rounds", "population", "epochs",
            "max_operations", "max_rules", "seed", "max_seconds"}, "Invalid config fields")
    require(type(config["family_id"]) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", config["family_id"]), "Invalid family ID")
    validate_config(config)
    require(type(state["demo"]) is bool, "Demo flag must be boolean")
    require(state["demo_omitted_seed_core"] == (DEMO_CORE if state["demo"] else None), "Invalid demo exclusion")
    require(type(state["base_data"]) is str and Path(state["base_data"]).is_absolute(), "Base data path must be absolute")
    for field in ("family_sha256", "base_atlas_sha256"):
        _state_hash(state[field], field)
    revision = state["code_revision"]
    require(revision is None or type(revision) is str and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision), "Invalid code revision")
    status = state["status"]
    require(status in ("AWAITING_PROPOSAL", "COMPLETED", "NO_CANDIDATE"), "Invalid run status")
    history = state["history"]
    require(type(history) is list and len(history) <= config["rounds"], "Invalid run history")
    _state_integer(state["round_index"], 1, config["rounds"], "round index")
    require((status == "COMPLETED" and len(history) == config["rounds"] and state["round_index"] == len(history))
            or (status != "COMPLETED" and len(history) < config["rounds"] and state["round_index"] == len(history) + 1),
            "Run status, round index and history disagree")
    has_binding = "current_candidate_sha256" in state
    require(has_binding == ("current_candidate_file_sha256" in state), "Incomplete current candidate binding")
    require(status == "NO_CANDIDATE" or has_binding, "Current candidate binding is missing")
    if has_binding:
        for field in ("current_candidate_sha256", "current_candidate_file_sha256"):
            _state_hash(state[field], field)
    if status == "NO_CANDIDATE":
        require(type(state.get("stop_reason")) is str and 1 <= len(state["stop_reason"]) <= 1000, "Missing bounded stop reason")
    else:
        require("stop_reason" not in state, "Unexpected stop reason")
    _replay_state_history(run_dir, state)
    return state


@contextmanager
def exclusive_run(run_dir):
    lock = run_dir / "cycle.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Run is already being advanced. If a previous process crashed, confirm it stopped before removing cycle.lock.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def validate_config(config):
    bounds = {"rounds": (1, 20), "population": (8, 256), "epochs": (1, 10),
              "max_operations": (1, 200000), "max_rules": (1, 5000), "seed": (0, 2**32 - 1)}
    for key, (low, high) in bounds.items():
        require(type(config.get(key)) is int and low <= config[key] <= high, f"{key} must be in {low}..{high}")
    seconds = config.get("max_seconds")
    require(type(seconds) in (int, float) and .001 <= seconds <= 60, "max_seconds must be .001..60 per proof attempt")


def validate_candidate(candidate, family_data):
    require(type(candidate) is dict and set(candidate) == {"format", "family_id", "family_sha256", "image_index_sha256", "matching", "candidate_sha256", "status"}, "Invalid candidate fields")
    require(candidate["format"] == "k22-candidate-v1" and candidate["status"] == "UNPROVED_CANDIDATE", "Invalid candidate format/status")
    family = verify_family(family_data)
    require(candidate["family_id"] == family_data["family_id"] and candidate["family_sha256"] == family.sha256, "Candidate family differs")
    require(candidate["image_index_sha256"] == family_data["image_index_sha256"], "Candidate product index differs")
    matching = candidate["matching"]
    require(type(matching) is list and len(matching) == 242, "Candidate needs 242 pairs")
    pairs = [edge(e) for e in matching]
    require(len({c for p in pairs for c in p}) == 484, "Candidate does not partition the cells")
    require(all(family.products[a] == family.products[b] for a, b in pairs), "Candidate pairs unequal products")
    expected = digest({"family_sha256": family.sha256, "matching": matching})
    require(candidate["candidate_sha256"] == expected, "Candidate hash differs")
    return candidate


def atlas_hash(problem):
    return digest(sorted(problem.submissions, key=lambda s: s["submission_id"]))


def _code_revision():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
            stderr=subprocess.DEVNULL, encoding="ascii", timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def round_dir(run_dir, state):
    return run_dir / f"round_{state['round_index']:03d}"


def load_memory(run_dir, state):
    config = state["config"]
    problem = load_problem(Path(state["base_data"]), config["family_id"])
    require(problem.family_sha256 == state["family_sha256"] and atlas_hash(problem) == state["base_atlas_sha256"],
            "Base inputs changed; start a new run and explicitly import verified feedback")
    omitted = state.get("demo_omitted_seed_core")
    require(omitted is None or (state.get("demo") is True and omitted == DEMO_CORE), "Invalid demo exclusion")
    submissions = {s["submission_id"]: s for s in problem.submissions if s["submission_id"] != omitted}
    feedback_dir = run_dir / "verified"
    paths = list((feedback_dir / "submissions").glob("*.json")) if feedback_dir.exists() else []
    if paths:
        verify_dataset(feedback_dir)
        checked_family = verify_family(problem.family)
        committed = {record["submission_id"] for record in state["history"]
                     if record.get("added_to_memory") is True}
        for path in paths:
            submission, _ = read_json(path)
            verify_submission(submission, {config["family_id"]: checked_family})
            if submission["submission_id"] in committed:
                submissions.setdefault(submission["submission_id"], submission)
    return Problem(problem.family, list(submissions.values()))


def choose_candidate(problem, config, round_index, seen):
    """A small CEM search against the exact current, independently checked atlas."""
    policy = Policy(problem)
    rng = random.Random(f"k22-chat-cycle:{config['seed']}:{round_index}")
    candidates = []
    for _ in range(config["epochs"]):
        batch = [policy.draw(rng) for _ in range(config["population"])]
        policy.update(sorted(batch, key=lambda s: (-s["score"], s["bits"]))[:max(1, len(batch) // 5)], .65)
        candidates.extend(batch)
    for sample in sorted(candidates, key=lambda s: (-s["score"], s["bits"])):
        if sample["known_core_violations"]:
            continue
        candidate = json.loads(canonical_bytes(problem.candidate(sample["bits"])))
        if candidate["candidate_sha256"] not in seen:
            validate_candidate(candidate, problem.family)
            return candidate, {"generated": len(candidates), "known_core_violations": 0,
                "score": sample["score"], "atlas_sha256": atlas_hash(problem), "core_count": len(problem.cores),
                "policy_states": len(policy.table)}
    return None, {"generated": len(candidates), "core_count": len(problem.cores), "atlas_sha256": atlas_hash(problem)}


def summary(state):
    history = state["history"]
    return {"format": "k22-chat-summary-v1", "status": state["status"], "demo": state["demo"],
            "completed_rounds": len(history), "requested_rounds": state["config"]["rounds"],
            "certified_attempts": sum(r["status"] == "CERTIFIED_SOURCE_TORSION" for r in history),
            "new_cores_relative_to_run": sum(r.get("added_to_memory", False) for r in history),
            "new_cores_relative_to_input_atlas": 0 if state["demo"] else sum(r.get("added_to_memory", False) for r in history),
            "outcomes": dict(Counter(r["status"] for r in history)),
            "next_prompt": f"round_{state['round_index']:03d}/prompt.json" if state["status"] == "AWAITING_PROPOSAL" else None,
            "scope": "Source torsion only. UNKNOWN is not torsion-freedom. Demo is a hand-authored rediscovery of a published obstruction; no new-result claim.",
            "llm_access": "Existing user-controlled chat; no API requests, keys, network calls, or executable model output."}


def save_state(run_dir, state):
    write(run_dir / "state.json", state)
    write(run_dir / "summary.json", summary(state))


def prepare_round(run_dir, state, problem, candidate=None):
    directory = round_dir(run_dir, state)
    if candidate is None:
        candidate, generation = choose_candidate(problem, state["config"], state["round_index"],
            {item["candidate_sha256"] for item in state["history"]})
    else:
        validate_candidate(candidate, problem.family)
        generation = {"source": "operator-supplied", "core_count": len(problem.cores),
            "known_core_violations": problem.score(problem.encode(candidate["matching"]))["known_core_violations"],
            "atlas_sha256": atlas_hash(problem)}
    write(directory / "generation.json", generation)
    if candidate is None:
        state["status"] = "NO_CANDIDATE"
        state["stop_reason"] = "Bounded CEM batch yielded no unseen candidate avoiding known cores; this is not exhaustion of the mathematical search space."
        save_state(run_dir, state)
        return
    messages = make_prompt(problem.family, candidate, feedback={"previous_rounds": state["history"][-3:],
        "verified_core_count": len(problem.cores), "demo": state["demo"]})
    write(directory / "candidate.json", candidate)
    write(directory / "prompt.json", messages)
    state["current_candidate_sha256"] = candidate["candidate_sha256"]
    state["current_candidate_file_sha256"] = digest(candidate)
    state["status"] = "AWAITING_PROPOSAL"
    save_state(run_dir, state)


def start_run(output, *, data=Path("data"), family_id="trinomial22", rounds=3, seed=22,
              population=32, epochs=2, max_operations=20000, max_rules=2000,
              max_seconds=10.0, candidate=None, demo=False):
    output, data = Path(output).absolute(), Path(data).absolute()
    config = dict(family_id=family_id, rounds=rounds, seed=seed, population=population,
        epochs=epochs, max_operations=max_operations, max_rules=max_rules, max_seconds=max_seconds)
    validate_config(config)
    require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "Use a new or empty run directory")
    require(not output.is_symlink(), "Run directory must not be a symlink")
    problem = load_problem(data, family_id)
    state = {"format": STATE_FORMAT, "status": "AWAITING_PROPOSAL", "config": config,
        "base_data": str(data), "family_sha256": problem.family_sha256, "base_atlas_sha256": atlas_hash(problem),
        "code_revision": _code_revision(), "round_index": 1, "history": [], "demo": bool(demo),
        "demo_omitted_seed_core": DEMO_CORE if demo else None}
    if demo:
        require(any(s["submission_id"] == DEMO_CORE for s in problem.submissions), "Demo requires the published reference core")
        problem = Problem(problem.family, [s for s in problem.submissions if s["submission_id"] != DEMO_CORE])
    if candidate is not None:
        candidate, _ = read_json(Path(candidate))
        validate_candidate(candidate, problem.family)
    output.mkdir(parents=True, exist_ok=True)
    write(output / "family.json", problem.family)
    prepare_round(output, state, problem, candidate)
    return summary(state)


def advance_run(run_dir, proposal_path):
    run_dir = Path(run_dir).absolute()
    with exclusive_run(run_dir):
        state = read_state(run_dir)
        require(state["status"] == "AWAITING_PROPOSAL", "Run is not waiting for a proposal")
        directory = round_dir(run_dir, state)
        candidate, _ = read_json(directory / "candidate.json")
        require(digest(candidate) == state["current_candidate_file_sha256"], "Saved candidate changed")
        require(state["current_candidate_sha256"] == candidate.get("candidate_sha256"), "Current candidate hash differs")
        proposal = read_proposal(Path(proposal_path), state["current_candidate_sha256"])
        problem = load_memory(run_dir, state)
        validate_candidate(candidate, problem.family)
        write(directory / "accepted_proposal.json", proposal)
        config = state["config"]
        started = time.monotonic()
        result = search(problem.family, candidate["matching"], proposal["targets"],
            max_operations=config["max_operations"], max_rules=config["max_rules"], max_seconds=config["max_seconds"])
        require(result.get("status") in ("CERTIFIED_SOURCE_TORSION", "UNKNOWN"), "Unexpected proof-search status")
        record = {"round": state["round_index"], "candidate_sha256": candidate["candidate_sha256"],
            "proposal_sha256": digest(proposal), "status": result["status"], "added_to_memory": False,
            "seconds": time.monotonic() - started, "core_count_before": len(problem.cores)}
        if result["status"] == "CERTIFIED_SOURCE_TORSION":
            # A discovery-engine success flag is not trusted. Reconstruct and replay
            # the entire public submission at this separate admission boundary.
            submission = prepare_submission(problem.family, candidate["matching"], result["certificate"])
            checked = verify_submission(submission, {config["family_id"]: verify_family(problem.family)})
            write(directory / "submission.json", submission)
            write(directory / "verification.json", checked)
            core = frozenset(tuple(sorted(map(tuple, e))) for e in submission["optional_core"])
            old_cores = [frozenset(tuple(sorted(map(tuple, e))) for e in s["optional_core"]) for s in problem.submissions]
            same = any(s["submission_id"] == submission["submission_id"] for s in problem.submissions)
            redundant = any(c <= core for c in old_cores)
            record.update(submission_id=submission["submission_id"], power_divides=checked["source_order_divides"],
                optional_core_edges=len(core), novelty="KNOWN_CORE" if same else "REDUNDANT_CORE" if redundant else "NEW_TO_RUN_MEMORY")
            if not redundant:
                feedback = run_dir / "verified"
                write(feedback / "families" / f"{config['family_id']}.json", problem.family)
                write(feedback / "submissions" / f"{submission['submission_id']}.json", submission)
                problem = Problem(problem.family, problem.submissions + [submission])
                record["added_to_memory"] = True
        write(directory / "search.json", result)
        record["core_count_after"] = len(problem.cores)
        state["history"].append(record)
        if len(state["history"]) >= config["rounds"]:
            state["status"] = "COMPLETED"
            save_state(run_dir, state)
        else:
            state["round_index"] += 1
            prepare_round(run_dir, state, problem)
        return summary(state)


def demo_run(output, *, data=Path("data")):
    """Reconstruct an already published proof from a hand-authored hypothesis."""
    fixture = Path(__file__).resolve().parents[1] / "examples" / "llm_demo"
    start_run(output, data=data, rounds=1, candidate=fixture / "candidate.json", demo=True)
    result = advance_run(output, fixture / "proposal.json")
    state = read_state(Path(output))
    problem = load_memory(Path(output), state)
    next_candidate, generation = choose_candidate(problem, state["config"], 2,
        {r["candidate_sha256"] for r in state["history"]})
    write(Path(output) / "after_feedback_generation.json", generation)
    if next_candidate:
        write(Path(output) / "after_feedback_candidate.json", next_candidate)
    result["post_feedback_candidate_generated"] = next_candidate is not None
    write(Path(output) / "summary.json", result)
    return result
