"""Tabular cross-entropy matching policy and an equal-sample uniform control.

Run from the repository root: python -m models.cem --output runs/cem-demo
This generates unproved candidates, not torsion-free certificates.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import random
import time

from .common import Problem, edge_key, fingerprint, load_problem, write_json


class Policy:
    """P(partner | product fiber, remaining-cell bitmask). No neural network."""

    def __init__(self, problem: Problem, exploration: float = .15):
        self.problem = problem
        self.exploration = exploration
        self.table: dict[tuple[int, int], dict[int, float]] = {}

    def draw(self, rng: random.Random, trained: bool = True) -> dict:
        bits = self.problem.forced_bits
        trajectory = []
        for fi, fiber in enumerate(self.problem.optional_fibers):
            mask = (1 << len(fiber)) - 1
            while mask:
                first_bit = mask & -mask
                i = first_bit.bit_length() - 1
                rest = mask ^ first_bit
                options = tuple(j for j in range(i + 1, len(fiber)) if rest >> j & 1)
                state = (fi, mask)
                probabilities = self.table.get(state)
                if trained and probabilities:
                    weights = [(1 - self.exploration) * probabilities[j] +
                               self.exploration / len(options) for j in options]
                    j = rng.choices(options, weights=weights, k=1)[0]
                else:
                    j = rng.choice(options)
                bits |= 1 << self.problem.edge_ids[edge_key((fiber[i], fiber[j]))]
                trajectory.append((state, j, options))
                mask = rest ^ (1 << j)
        return {"bits": bits, "trajectory": trajectory, **self.problem.score(bits)}

    def update(self, elite: list[dict], learning_rate: float):
        counts = defaultdict(Counter)
        choices = {}
        for sample in elite:
            for state, partner, options in sample["trajectory"]:
                counts[state][partner] += 1
                choices[state] = options
        for state, counts_at_state in counts.items():
            options = choices[state]
            previous = self.table.get(state, {j: 1 / len(options) for j in options})
            total = sum(counts_at_state.values())
            self.table[state] = {j: (1 - learning_rate) * previous[j] +
                                learning_rate * counts_at_state[j] / total for j in options}

    def export(self) -> list[dict]:
        return [{"fiber": fi, "remaining_mask": mask,
                 "partner_probabilities": probabilities}
                for (fi, mask), probabilities in sorted(self.table.items())]


def statistics(samples: list[dict]) -> dict:
    count = len(samples)
    return {"samples": count,
            "unique_matchings": len({sample["bits"] for sample in samples}),
            "zero_known_core_violations": sum(sample["known_core_violations"] == 0 for sample in samples),
            **{f"mean_{key}": sum(sample[key] for sample in samples) / max(1, count)
               for key in ("score", "known_core_violations", "core_pressure", "novelty")}}


def rng_stream(seed: int, name: str) -> random.Random:
    """One isolated continuous stream per seed, arm, and phase."""
    return random.Random(f"k22-public-cem-v1:{seed}:{name}")


def benchmark(problem: Problem, *, seed: int = 22, epochs: int = 10,
              population: int = 128, heldout: int = 128,
              elite_fraction: float = .2, learning_rate: float = .65,
              exploration: float = .15) -> tuple[dict, Policy, dict]:
    policy = Policy(problem, exploration)
    samples = {arm: [] for arm in ("cem", "uniform")}
    generators = {arm: rng_stream(seed, f"training:{arm}") for arm in samples}
    history = []
    for epoch in range(epochs):
        current = {arm: [policy.draw(generators[arm], trained=(arm == "cem"))
                         for _ in range(population)] for arm in samples}
        elite = sorted(current["cem"], key=lambda sample: (-sample["score"], sample["bits"]))[:max(1, int(population * elite_fraction))]
        policy.update(elite, learning_rate)
        history.append({"epoch": epoch + 1, **{arm: statistics(pop) for arm, pop in current.items()}})
        for arm, pop in current.items():
            for sample in pop:
                sample.pop("trajectory")
            samples[arm].extend(pop)
    hold = {}
    for arm in samples:
        generator = rng_stream(seed, f"heldout:{arm}")
        hold[arm] = [policy.draw(generator, trained=(arm == "cem")) for _ in range(heldout)]
        for sample in hold[arm]:
            sample.pop("trajectory")
    summary = {"format": "k22-cem-benchmark-v1", "family_id": problem.family["family_id"],
               "family_sha256": problem.family_sha256,
               "image_index_sha256": problem.family["image_index_sha256"],
               "atlas_sha256": fingerprint(sorted((s["submission_id"], fingerprint(s))
                                                    for s in problem.submissions)),
               "core_count": len(problem.cores), "seed": seed, "epochs": epochs,
               "population": population, "heldout_per_arm": heldout,
               "elite_fraction": elite_fraction, "elite_count": max(1, int(population * elite_fraction)),
               "learning_rate": learning_rate, "exploration": exploration,
               "generated_per_arm": epochs * population + heldout,
               "rng_scheme": "one-isolated-continuous-stream-per-seed-phase-arm",
               "reward": "-1000*violations - sum(2**(-min(missing_edges,16))) + 0.05*novelty",
               "training": {arm: statistics(pop) for arm, pop in samples.items()},
               "heldout": {arm: statistics(pop) for arm, pop in hold.items()},
               "heldout_candidate_hashes": {arm: [problem.candidate(s["bits"])["candidate_sha256"] for s in pop]
                                             for arm, pop in hold.items()},
               "history": history, "policy_states": len(policy.table),
               "scope": "Equal generated-sample budgets, not equal wall time. No proof search is run. Avoiding known cores is not torsion-freeness."}
    for arm in samples:
        samples[arm].extend(hold[arm])
    return summary, policy, samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--family", default="trinomial22")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=22)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--population", type=int, default=128)
    parser.add_argument("--heldout", type=int, default=128)
    parser.add_argument("--elite-fraction", type=float, default=.2)
    parser.add_argument("--learning-rate", type=float, default=.65)
    parser.add_argument("--exploration", type=float, default=.15)
    parser.add_argument("--save-top", type=int, default=8)
    args = parser.parse_args()
    if min(args.epochs, args.population, args.heldout, args.save_top) < 1:
        parser.error("epochs, population, heldout, save-top must be positive")
    if not 0 < args.elite_fraction <= 1 or not 0 < args.learning_rate <= 1 or not 0 <= args.exploration <= 1:
        parser.error("elite-fraction and learning-rate must be in (0,1]; exploration in [0,1]")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a new or empty output directory to preserve previous runs")
    args.output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    problem = load_problem(args.data, args.family, args.output / "input_verification.json")
    verified_at = time.monotonic()
    summary, policy, samples = benchmark(problem, seed=args.seed, epochs=args.epochs,
                                         population=args.population, heldout=args.heldout,
                                         elite_fraction=args.elite_fraction,
                                         learning_rate=args.learning_rate,
                                         exploration=args.exploration)
    summary["input_verification_seconds"] = verified_at - start
    summary["generation_and_scoring_seconds"] = time.monotonic() - verified_at
    write_json(args.output / "policy.json", {"format": "k22-tabular-policy-v1",
               "family_sha256": problem.family_sha256, "seed": args.seed,
               "atlas_sha256": summary["atlas_sha256"],
               "exploration": args.exploration, "optional_fibers": problem.optional_fibers,
               "states": policy.export()})
    for arm, population in samples.items():
        unique = {sample["bits"]: sample for sample in population}
        top = sorted(unique.values(), key=lambda s: (-s["score"], s["bits"]))[:args.save_top]
        for rank, sample in enumerate(top):
            folder = args.output / "selected" / arm / f"case{rank:03d}"
            write_json(folder / "candidate.json", problem.candidate(sample["bits"]))
            write_json(folder / "ranking.json", {k: v for k, v in sample.items() if k != "bits"})
    write_json(args.output / "metrics.json", summary)
    print(f"Wrote {args.output / 'metrics.json'}; candidates remain unproved.")


if __name__ == "__main__":
    main()
