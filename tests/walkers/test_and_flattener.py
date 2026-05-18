from pysmt.shortcuts import And, Iff, Or, Symbol, is_valid

from enumerators.walkers.and_flattener import AndFlattener
import pytest

TEST_CASES = [
    (
        lambda: And(Symbol("a"), And(Symbol("b"), Symbol("c"))),
        lambda: frozenset([Symbol("a"), Symbol("b"), Symbol("c")]),
    ),
    (
        lambda: And(Symbol("a"), Or(Symbol("b"), And(Symbol("b"), Symbol("c")))),
        lambda: frozenset([Symbol("a"), Or(Symbol("b"), And(Symbol("b"), Symbol("c")))]),
    ),
    (
        lambda: And(
            And(
                Symbol("a"),
                And(Symbol("b"), Symbol("c")),
                Or(Symbol("a"), Symbol("c")),
            ),
            And(Symbol("a"), Symbol("c")),
        ),
        lambda: frozenset([Symbol("a"), Symbol("b"), Symbol("c"), Or(Symbol("a"), Symbol("c"))]),
    ),
]


@pytest.mark.parametrize("build_formula, build_expected", TEST_CASES)
def test_and_flattener(build_formula, build_expected):
    formula = build_formula()
    expected = build_expected()
    flattener = AndFlattener()
    result = flattener.flatten(formula)
    assert result == expected, f"Expected {expected}, got {result}"
    assert is_valid(Iff(formula, And(result))), (
        "The original formula should be equivalent to the conjunction of the flattened components"
    )
