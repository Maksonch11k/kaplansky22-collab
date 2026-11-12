"""Fast model tests: python -m unittest models.test_cem -v."""
import random
import unittest

from models.cem import Policy, benchmark, rng_stream
from models.common import Problem, edge_key


def toy_problem():
    # Deliberately a small combinatorial fixture, not a verified group family.
    identity = [[0, 0, 0], [1, 1, 1]]
    family = {"family_id": "toy", "n": 4, "m": 4,
              "left": [identity] * 4, "right": [identity] * 4,
              "image_index_sha256": "fixture-only"}
    return Problem(family, [])


class CEMTests(unittest.TestCase):
    def test_draw_is_a_perfect_matching(self):
        problem = toy_problem()
        policy = Policy(problem)
        for seed in range(10):
            matching = problem.decode(policy.draw(random.Random(seed))["bits"])
            cells = [cell for pair in matching for cell in pair]
            self.assertEqual(len(matching), 8)
            self.assertEqual(len(set(cells)), 16)
            self.assertEqual(set(cells), {(i, j) for i in range(1, 5) for j in range(1, 5)})

    def test_elite_update_is_a_distribution(self):
        policy = Policy(toy_problem())
        rng = random.Random(1)
        population = [policy.draw(rng) for _ in range(8)]
        policy.update(population[:2], .65)
        for distribution in policy.table.values():
            self.assertAlmostEqual(sum(distribution.values()), 1)
            self.assertTrue(all(0 <= p <= 1 for p in distribution.values()))

    def test_equal_budgets_and_reproducibility(self):
        options = dict(seed=8, epochs=2, population=8, heldout=10)
        first, _, _ = benchmark(toy_problem(), **options)
        second, _, _ = benchmark(toy_problem(), **options)
        self.assertEqual(first, second)
        self.assertEqual(first["generated_per_arm"], 26)
        for arm in ("cem", "uniform"):
            self.assertEqual(first["training"][arm]["samples"], 16)
            self.assertEqual(first["heldout"][arm]["samples"], 10)

    def test_seed_streams_are_isolated(self):
        streams = [rng_stream(seed, name) for seed in (22, 23)
                   for name in ("training:cem", "training:uniform", "heldout:cem", "heldout:uniform")]
        sequences = [tuple(rng.getrandbits(64) for _ in range(8)) for rng in streams]
        self.assertEqual(len(set(sequences)), len(sequences))

    def test_core_scoring_and_unproved_status(self):
        problem = toy_problem()
        bit = 1 << problem.edge_ids[edge_key(((1, 1), (1, 2)))]
        problem.cores = (bit,)
        self.assertEqual(problem.score(bit)["known_core_violations"], 1)
        self.assertEqual(problem.score(0)["known_core_violations"], 0)
        self.assertEqual(problem.candidate(bit)["status"], "UNPROVED_CANDIDATE")


if __name__ == "__main__":
    unittest.main()
