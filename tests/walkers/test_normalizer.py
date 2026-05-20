import pytest
from allsat_cnf.utils import MathSAT5Solver
from pysmt.fnode import FNode
from pysmt.shortcuts import And, Solver

from enumerators.walkers.normalizer import NormalizerWalker


@pytest.fixture
def converter():
    with Solver("msat") as msat:
        msat: MathSAT5Solver
        yield msat.converter


def test_normalizer_walker(x, y, a, converter):
    y_le_x = y <= x
    x_le_y = x <= y
    x_le_y_equiv = x + (-1 * y) <= 0
    x_ge_2 = x >= 2
    x_ge_2_equiv = 2 * x >= 4

    norm_walker = NormalizerWalker(converter)
    x_le_y_norm = norm_walker.normalize(x_le_y)
    assert x_le_y_norm == norm_walker.normalize(x_le_y_equiv)
    x_ge_2_norm = norm_walker.normalize(x_ge_2)
    assert x_ge_2_norm == norm_walker.normalize(x_ge_2_equiv)

    phi: FNode = And(
        a,
        (x_le_y | ~y_le_x),
        (x_le_y_equiv & x_ge_2),
        x_ge_2_equiv,
    )

    normal = norm_walker.normalize(phi)

    assert normal == phi.substitute(
        {
            x_le_y: x_le_y_norm,
            x_le_y_equiv: x_le_y_norm,
            x_ge_2: x_ge_2_norm,
            x_ge_2_equiv: x_ge_2_norm,
        }
    )
