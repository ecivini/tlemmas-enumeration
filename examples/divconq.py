from pysmt.shortcuts import Symbol, REAL
from tlemma_enum.solvers.mathsat_divide_and_conquer import MathSATDivideAndConquerEnumerator

# Create variables
x = Symbol("x", REAL)
y = Symbol("y", REAL)

# Define a formula
phi = (x + y >= 1) | (x + y <= 0)

# Enumerate using AllSMT enumeration
parallel_workers = 4
enumerator = MathSATDivideAndConquerEnumerator(parallel_procs=parallel_workers)
result = enumerator.check_all_sat(phi)

# Get the theory lemmas
lemmas = enumerator.get_theory_lemmas()
print(f"Found {len(lemmas)} theory lemmas")
print(f"Model count: {enumerator.get_models_count()}")
