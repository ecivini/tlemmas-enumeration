import pytest
from allsat_cnf.utils import MathSAT5Solver
from pysmt.fnode import FNode
from pysmt.shortcuts import BOOL, LE, REAL, And, Not, Or, Plus, Real, Solver, Symbol, Times

from enumerators.walkers.normalizer import NormalizerWalker


@pytest.fixture
def converter():
    with Solver("msat") as msat:
        msat: MathSAT5Solver
        yield msat.converter


def test_normalizer_walker(converter):
    x = Symbol("X", REAL)
    y = Symbol("Y", REAL)
    flag = Symbol("F", BOOL)

    y_le_x = LE(y, x)
    x_le_y = LE(x, y)
    x_le_y_equiv = LE(Plus(x, Times(Real(-1), y)), Real(0))
    x_ge_2 = LE(Real(2), x)
    x_ge_2_equiv = LE(Real(4), Times(Real(2), x))

    norm_walker = NormalizerWalker(converter)
    x_le_y_norm = norm_walker.normalize(x_le_y)
    assert x_le_y_norm == norm_walker.normalize(x_le_y_equiv)
    x_ge_2_norm = norm_walker.normalize(x_ge_2)
    assert x_ge_2_norm == norm_walker.normalize(x_ge_2_equiv)

    phi: FNode = And(
        flag,
        Or(x_le_y, Not(y_le_x)),
        And(
            x_le_y_equiv,
            x_ge_2,
        ),
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
