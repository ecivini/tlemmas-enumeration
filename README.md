# Implementation of the algorithms presented in the paper "Beyond Eager Encodings: A Theory-Agnostic Approach to Theory-Lemma Enumeration in SMT"

## Installation

### Prerequisites

- Python 3.11 or higher
- GCC and build tools (for compiling MathSAT bindings)

### Installation procedure

```bash
# Install the package
$ pip install https://github.com/ecivini/tlemmas-enumeration.git

# Install MathSAT
$ pysmt-install --msat
```

## Architecture

Solvers use a decorator pattern based on the `SMTEnumerator` interface:

- **Base solvers** implement core enumeration algorithms:
  - `MathSATTotalEnumerator`: single-shot enumeration
  - `MathSATDivideAndConquerEnumerator`: parallel divide-&-conquer enumeration
- **Wrapper classes** add cross-cutting concerns:
  - `WithProjectionWrapper`: restricts to theory atoms only
  - `WithPartitioningWrapper`: partitions atoms in symbol-disjoint components

E.g.:

```python
from tlemma_enum.solvers import MathSATDivideAndConquerEnumerator
from tlemma_enum.solvers import WithPartitioningWrapper

enumerator = WithPartitioningWrapper(
    MathSATDivideAndConquerEnumerator(parallel_procs=4)
)
```

Note that `WithPartitioningWrapper` already projects onto theory atoms
internally, so wrapping it in `WithProjectionWrapper` is redundant.
See `examples/` for more usage patterns.

## Quick Start

```python
from pysmt.shortcuts import Symbol, REAL
from tlemma_enum.solvers.mathsat_total import MathSATTotalEnumerator

# Create variables
x = Symbol("x", REAL)
y = Symbol("y", REAL)

# Define a formula
phi = (x + y >= 1) | (x + y <= 0)

# Enumerate using Divide & Conquer enumeration
enumerator = MathSATTotalEnumerator()
result = enumerator.check_all_sat(phi)

# Get the theory lemmas
lemmas = enumerator.get_theory_lemmas()
print(f"Found {len(lemmas)} theory lemmas")
print(f"Model count: {enumerator.get_models_count()}")
```

