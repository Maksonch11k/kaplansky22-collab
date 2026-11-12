# Kaplansky22: an open collaboration

We search for 22×22 support constructions towards a zero-divisor counterexample over **F₂ in a torsion-free group**. **No counterexample is known from this project.** [Русская версия](README.md).

The repository contains two ordered affine-image families, **532 independently replayable obstruction certificates** (235 parallel, 297 trinomial), a standard-library verifier, a runnable tabular cross-entropy generator, and an ExtraTrees/SAT baseline with **681 historical training records and 155 features**.

```bash
git clone https://github.com/Maksonch11k/kaplansky22-collab.git
cd kaplansky22-collab
python -m k22 verify --data data
python -m unittest discover -s tests
python -m models.cem --family trinomial22 --epochs 10 --population 128 --output runs/demo
```

Python 3.11+ is sufficient for proof checking and CEM. For ExtraTrees and SAT:

```bash
python -m pip install -e ".[ml]"
python -m models.mlsat train --output runs/ml
python -m models.mlsat generate --family parallel22 --count 4 --output runs/sat
```

The learned target is **historical bounded UNKNOWN**, not torsion-freedom. CEM learns to avoid certified cores; it does not recognize every possible torsion obstruction. The historical proof-discovery engine is not bundled. New proofs can be produced by any external tool and must pass the independent verifier.

An obstruction proves nontrivial finite-order torsion in the **presented source group**, and in every matching extension of its core within the same fixed ordered family. It does **not** automatically rule out torsion-free quotients. A bounded checker timing out is not a proof of torsion-freedom.

To participate, choose an [issue](https://github.com/Maksonch11k/kaplansky22-collab/issues), fork the repository, give your agent [AGENTS.md](AGENTS.md), and open a pull request. No agent registry, credentials or shared remote execution service is needed. See [CONTRIBUTING.md](CONTRIBUTING.md) and [model architecture](docs/MODELS.md).

The new software is MIT-licensed; mathematical data and feature tables are dedicated under CC0-1.0. CI replays certificates with the base-branch verifier on pull requests; verifier and workflow changes still require human review.
