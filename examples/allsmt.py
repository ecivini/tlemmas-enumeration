from pysmt.shortcuts import Symbol, REAL
from enumerators.solvers.mathsat_total import MathSATTotalEnumerator

# Create variables
x = Symbol("x", REAL)
y = Symbol("y", REAL)

# Define a formula
phi = (x + y >= 1) | (x + y <= 0)

# Enumerate using AllSMT enumeration
enumerator = MathSATTotalEnumerator()
result = enumerator.check_all_sat(phi)

# Get the theory lemmas
lemmas = enumerator.get_theory_lemmas()
print(f"Found {len(lemmas)} theory lemmas")
print(f"Model count: {enumerator.get_models_count()}")
