from typing import Callable
from pysmt.fnode import FNode
from pysmt.shortcuts import is_valid, And

from enumerators.walkers.and_flattener import AndFlattener
import pytest

FormulaBuilder = Callable[[dict[str, FNode]], FNode]
FormulasConjunctionBuilder = Callable[[dict[str, FNode]], frozenset[FNode]]
TEST_CASES: list[tuple[FormulaBuilder, FormulasConjunctionBuilder]] = [
    (
        lambda s: s["A"] & (s["B"] & s["C"]),
        lambda s: frozenset([s["A"], s["B"], s["C"]]),
    ),
    (
        lambda s: s["A"] & (s["B"] | (s["B"] & s["C"])),
        lambda s: frozenset([s["A"], (s["B"] | (s["B"] & s["C"]))]),
    ),
    (
        lambda s: And(
            s["A"],
            (s["B"] & s["C"]),
            (s["A"] | s["C"]),
        )
        & (s["A"] & s["C"]),
        lambda s: frozenset([s["A"], s["B"], s["C"], (s["A"] | s["C"])]),
    ),
]


@pytest.mark.parametrize("build_formula, build_expected", TEST_CASES)
def test_and_flattener(
    build_formula: FormulaBuilder,
    build_expected: FormulasConjunctionBuilder,
    all_vars: dict[str, FNode],
) -> None:
    formula = build_formula(all_vars)
    expected = build_expected(all_vars)
    flattener = AndFlattener()
    result = flattener.flatten(formula)
    assert result == expected, f"Expected {expected}, got {result}"
    assert is_valid(formula.Iff(And(result))), (
        "The original formula should be equivalent to the conjunction of the flattened components"
    )
