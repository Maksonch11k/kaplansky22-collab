"""ExtraTrees baseline, exact SAT proposals, and the historical 155 features.

Model scores predict an old bounded checker's UNKNOWN label, NOT torsion-freedom.
SAT and ML produce candidates only; certificates are checked separately by k22.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import time

from .common import load_problem, write_json

MODEL_PARAMETERS = dict(n_estimators=400, min_samples_leaf=4, max_features=.7,
                        class_weight="balanced", random_state=2266, n_jobs=1)
LABEL = "old_bounded_unknown"
WARNING = "Predicts historical bounded UNKNOWN, not torsion-freedom."


def read_records(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("format") != "k22-training-records-v1":
        raise ValueError("Unsupported training format")
    rows = value["records"]
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("Need at least two training records")
    names = sorted(rows[0]["features"])
    if not names:
        raise ValueError("Empty features")
    for row in rows:
        if type(row[LABEL]) is not int or row[LABEL] not in (0, 1):
            raise ValueError("Label must be integer 0 or 1")
        feature_vector(row["features"], names)
    if {r[LABEL] for r in rows} != {0, 1}:
        raise ValueError("Both historical classes are needed")
    return rows, names


def feature_vector(features, names):
    if set(features) != set(names):
        raise ValueError("Feature names must exactly match the training schema")
    result = []
    for name in names:
        value = features[name]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Non-finite or non-numeric feature: {name}")
        result.append(float(value))
    return result


def fit(rows, names):
    from sklearn.ensemble import ExtraTreesClassifier
    model = ExtraTreesClassifier(**MODEL_PARAMETERS)
    model.fit([feature_vector(r["features"], names) for r in rows],
              [r[LABEL] for r in rows])
    return model


def evaluate(rows, names, seed):
    """Group by matching hash before splitting; don't leak repeat matchings."""
    from sklearn.metrics import balanced_accuracy_score, roc_auc_score
    from sklearn.model_selection import GroupShuffleSplit
    groups = [r["matching_sha256"] for r in rows]
    split = GroupShuffleSplit(n_splits=1, test_size=.25, random_state=seed)
    train, test = next(split.split(rows, groups=groups))
    train_rows, test_rows = [rows[i] for i in train], [rows[i] for i in test]
    if {r[LABEL] for r in train_rows} != {0, 1}:
        raise ValueError("Training split lacks a class; choose another seed")
    model = fit(train_rows, names)
    scores = model.predict_proba([feature_vector(r["features"], names)
                                  for r in test_rows])[:, list(model.classes_).index(1)]
    labels = [r[LABEL] for r in test_rows]
    return {"split": "grouped 75/25 holdout by historical matching hash",
            "seed": seed, "train_samples": len(train), "test_samples": len(test),
            "auc": float(roc_auc_score(labels, scores)) if len(set(labels)) == 2 else None,
            "balanced_accuracy": float(balanced_accuracy_score(labels, scores >= .5)),
            "warning": "Same historical campaigns; does not establish family transfer or torsion-free survival."}


def rank_mod(matrix, prime):
    rows = [[value % prime for value in row] for row in matrix]
    rank = 0
    for column in range(len(rows[0]) if rows else 0):
        pivot = next((i for i in range(rank, len(rows)) if rows[i][column]), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        inv = pow(rows[rank][column], -1, prime)
        rows[rank] = [(x * inv) % prime for x in rows[rank]]
        for i in range(rank + 1, len(rows)):
            coefficient = rows[i][column]
            rows[i] = [(x - coefficient * y) % prime for x, y in zip(rows[i], rows[rank])]
        rank += 1
        if rank == len(rows):
            break
    return rank


def extract_features(candidate, trace):
    """Reimplement the historical feature definition from explicit inputs.

    trace = {active_generators: [positive IDs], relators: [[signed IDs], ...]}.
    This function does not certify the reduction or produce a proof. A different
    simplifier can change the feature distribution even for the same group.
    """
    import numpy as np
    matching = candidate["matching"]
    cells = [tuple(cell) for edge in matching for cell in edge]
    if len(matching) != 242 or sorted(cells) != [(i, j) for i in range(1, 23) for j in range(1, 23)]:
        raise ValueError("Expected a full 22x22 matching")
    generators, relators = trace["active_generators"], trace["relators"]
    if len(set(generators)) != len(generators) or any(type(g) is not int or g < 1 for g in generators):
        raise ValueError("Invalid active generators")
    if any(type(x) is not int or abs(x) not in generators for r in relators for x in r):
        raise ValueError("Relators use inactive generators")
    features = {}

    def stats(prefix, values):
        values = list(values)
        array = np.asarray(values or [0], dtype=float)
        measurements = dict(count=len(values), min=array.min(), max=array.max(),
                            mean=array.mean(), std=array.std(), q25=np.quantile(array, .25),
                            median=np.median(array), q75=np.quantile(array, .75))
        features.update({prefix + "_" + key: float(value) for key, value in measurements.items()})

    for side, name in ((0, "row"), (1, "col")):
        adjacency = np.zeros((22, 22), dtype=int)
        for a, b in matching:
            i, j = a[side] - 1, b[side] - 1
            adjacency[i, j] += 1
            adjacency[j, i] += 1
        multiplicities = adjacency[np.triu_indices(22, 1)]
        simple = (adjacency > 0).astype(int)
        stats(name + "_multiplicity", multiplicities)
        stats(name + "_distinct_neighbors", simple.sum(axis=1))
        features[name + "_triangles"] = float(np.trace(simple @ simple @ simple) / 6)
        for i, value in enumerate(np.linalg.eigvalsh(adjacency)):
            features[f"{name}_eigen_{i}"] = float(value)
        for k in range(1, 7):
            features[f"{name}_pairs_mult_{k}"] = float((multiplicities == k).sum())
    features["positive_slope"] = sum((a[0] - b[0]) * (a[1] - b[1]) > 0 for a, b in matching) / 242
    stats("row_distance", (abs(a[0] - b[0]) for a, b in matching))
    stats("col_distance", (abs(a[1] - b[1]) for a, b in matching))
    lengths = list(map(len, relators))
    features["active_generators"] = len(generators)
    stats("relator_length", lengths)
    features["letters"] = sum(lengths)
    for cutoff in (2, 3, 4, 5, 6, 8, 10, 12, 16, 24):
        features[f"rels_length_le_{cutoff}"] = sum(length <= cutoff for length in lengths)
    occurrences = Counter(abs(x) for word in relators for x in word)
    stats("gen_occurrences", (occurrences[g] for g in generators))
    features["free_generators"] = sum(occurrences[g] == 0 for g in generators)
    exponents = [[word.count(g) - word.count(-g) for g in generators] for word in relators]
    for prime in (2, 3):
        features[f"abelian_rank_mod{prime}"] = len(generators) - rank_mod(exponents, prime)
    features["proper_power_relators"] = sum(any(len(word) % k == 0 and word[:k] * (len(word) // k) == word
        for k in range(1, len(word) // 2 + 1)) for word in relators)
    for length in (2, 3):
        grams = Counter(tuple((word + word)[i:i + length]) for word in relators for i in range(len(word)))
        stats(f"cyclic_ngram{length}", grams.values())
    return features


def generate(args):
    import z3
    from itertools import combinations
    from .common import edge_key
    problem = load_problem(args.data, args.family)
    solver = z3.Solver()
    solver.set(random_seed=args.seed, timeout=args.timeout_ms)
    variables = {edge: z3.Bool(f"edge_{i}") for i, edge in enumerate(problem.edges)}
    for fiber in problem.fibers:
        for cell in fiber:
            solver.add(z3.PbEq([(variables[edge_key((cell, other))], 1)
                                for other in fiber if other != cell], 1))
    for submission in problem.submissions:
        solver.add(z3.Or([z3.Not(variables[edge_key(edge)]) for edge in submission["optional_core"]]))
    optional = [edge_key(edge) for fiber in problem.optional_fibers for edge in combinations(fiber, 2)]
    rng = random.Random(args.seed)
    candidates = []
    stop = "requested_count"
    for index in range(args.count):
        assumptions = [variables[edge] for edge in rng.sample(optional, min(5, len(optional)))]
        while True:
            status = solver.check(*assumptions)
            if status == z3.sat:
                break
            if status == z3.unknown:
                stop = "solver_unknown: " + solver.reason_unknown()
                break
            if not assumptions:
                stop = "exhausted_known_core_avoiding_space"
                break
            assumptions.pop()
        if status != z3.sat:
            break
        model = solver.model()
        chosen = [edge for edge, variable in variables.items() if z3.is_true(model.eval(variable))]
        bits = problem.encode(chosen)
        if len(chosen) != 242 or problem.score(bits)["known_core_violations"]:
            raise RuntimeError("Invalid SAT proposal")
        candidate = problem.candidate(bits)
        write_json(args.output / f"candidate_{index:04d}.json", candidate)
        candidates.append(candidate["candidate_sha256"])
        solver.add(z3.Or([z3.Not(variables[edge]) for edge in chosen]))
    summary = {"format": "k22-sat-proposals-v1", "family_sha256": problem.family_sha256,
               "known_cores": len(problem.cores), "seed": args.seed, "requested": args.count,
               "generated": len(candidates), "stop": stop, "z3_version": z3.get_version_string(),
               "candidates": candidates, "status": "UNPROVED_CANDIDATES"}
    write_json(args.output / "summary.json", summary)
    print(json.dumps(summary))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("train", "rank"):
        sub = commands.add_parser(command)
        sub.add_argument("--training", type=Path, default=Path("models/training_records.json"))
        sub.add_argument("--output", type=Path, required=True)
        if command == "train":
            sub.add_argument("--seed", type=int, default=22)
        else:
            sub.add_argument("--candidates", type=Path, required=True,
                             help="JSON list of {candidate_sha256, features}")
    sub = commands.add_parser("features")
    for name in ("candidate", "trace", "output"):
        sub.add_argument("--" + name, type=Path, required=True)
    sub = commands.add_parser("generate")
    sub.add_argument("--data", type=Path, default=Path("data"))
    sub.add_argument("--family", choices=("parallel22", "trinomial22"), default="parallel22")
    sub.add_argument("--count", type=int, default=4)
    sub.add_argument("--seed", type=int, default=22)
    sub.add_argument("--timeout-ms", type=int, default=10000)
    sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        if not 1 <= args.count <= 10000 or not 1 <= args.timeout_ms <= 3600000:
            parser.error("count must be 1..10000 and timeout-ms 1..3600000")
        generate(args)
        return
    if args.command == "features":
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        trace = json.loads(args.trace.read_text(encoding="utf-8"))
        write_json(args.output, [{"candidate_sha256": candidate["candidate_sha256"],
                                 "features": extract_features(candidate, trace)}])
        return
    rows, names = read_records(args.training)
    import numpy
    import sklearn
    started = time.monotonic()
    if args.command == "train":
        evaluation = evaluate(rows, names, args.seed)
        model = fit(rows, names)
        summary = {"format": "k22-ml-training-v1", "warning": WARNING,
                   "parameters": MODEL_PARAMETERS, "label": LABEL, "samples": len(rows),
                   "positive_labels": sum(r[LABEL] for r in rows), "features": names,
                   "training_table_sha256": hashlib.sha256(args.training.read_bytes()).hexdigest(),
                   "evaluation": evaluation, "numpy_version": numpy.__version__,
                   "sklearn_version": sklearn.__version__, "seconds": time.monotonic() - started,
                   "feature_importance": dict(zip(names, map(float, model.feature_importances_))),
                   "persistence": "Recipe and inputs, no executable pickle; rank retrains deterministically."}
        write_json(args.output / "training.json", summary)
        print(json.dumps({k: summary[k] for k in ("samples", "positive_labels", "evaluation", "warning")}))
    else:
        candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("Expected a nonempty list of candidate feature records")
        model = fit(rows, names)
        scores = model.predict_proba([feature_vector(r["features"], names) for r in candidates])[:, list(model.classes_).index(1)]
        ranking = sorted(({"candidate_sha256": r["candidate_sha256"],
                           "score_old_bounded_unknown": float(score)}
                          for r, score in zip(candidates, scores)),
                         key=lambda r: (-r["score_old_bounded_unknown"], r["candidate_sha256"]))
        write_json(args.output, {"format": "k22-ml-ranking-v1", "warning": WARNING,
                                "training_table_sha256": hashlib.sha256(args.training.read_bytes()).hexdigest(),
                                "ranking": ranking})
        print(json.dumps({"ranked": len(ranking), "warning": WARNING}))


if __name__ == "__main__":
    main()
