"""tests for module formula"""

from pysmt.fnode import FNode
from pysmt.shortcuts import And, BOOL, FALSE, LE, Not, Or, Plus, REAL, Real, Symbol, TRUE, Times

import enumerators.formula as formula
from enumerators.solvers.mathsat_total import MathSATTotalEnumerator


def test_get_symbols():
    """tests for formula.get_symbols()"""
    phi = And(
        Symbol("F", BOOL),
        LE(Symbol("X", REAL), Symbol("Y", REAL)),
        Symbol("Z", BOOL),
    )
    assert len(formula.get_symbols(phi)) == 4, "the normalized formula has 4 symbols"
    phi = Or(
        And(
            Symbol("F", BOOL),
            LE(Symbol("X", REAL), Symbol("Y", REAL)),
            LE(Symbol("Y", REAL), Symbol("X", REAL)),
            Symbol("Z", BOOL),
        ),
        Not(LE(Symbol("X", REAL), Symbol("Y", REAL))),
        Not(LE(Symbol("Y", REAL), Symbol("X", REAL))),
    )
    assert (
        len(formula.get_symbols(phi)) == 4
    ), "the normalized formula has 4 symbols, even if some appear more than once"


def test_get_atoms():
    """tyests for get atoms"""
    phi = And(
        Symbol("F", BOOL),
        LE(Symbol("X", REAL), Symbol("Y", REAL)),
        LE(Symbol("Y", REAL), Symbol("X", REAL)),
        Symbol("Z", BOOL),
    )
    assert len(formula.get_atoms(phi)) == 4, "the normalized formula has 4 atoms"
    phi = Or(
        And(
            Symbol("F", BOOL),
            LE(Symbol("X", REAL), Symbol("Y", REAL)),
            LE(Symbol("Y", REAL), Symbol("X", REAL)),
            Symbol("Z", BOOL),
        ),
        Not(LE(Symbol("X", REAL), Symbol("Y", REAL))),
        Not(LE(Symbol("Y", REAL), Symbol("X", REAL))),
    )
    assert len(formula.get_atoms(phi)) == 4, "the normalized formula has 4 atoms, even if some appear more than once"


def test_normalization():
    """tests for get_normalized"""
    solver = MathSATTotalEnumerator()
    converter = solver.get_converter()
    # all atoms are different
    phi = And(
        Symbol("F", BOOL),
        LE(Symbol("X", REAL), Symbol("Y", REAL)),
        LE(Symbol("Y", REAL), Symbol("X", REAL)),
        Symbol("Z", BOOL),
    )
    normal = formula.get_normalized(phi, converter)
    assert len(formula.get_atoms(normal)) == 4, "the normalized formula has 4 atoms"
    assert len(formula.get_atoms(normal)) == len(
        formula.get_atoms(phi)
    ), "different atoms should be normalized into different atoms"
    # 1st and 3rd LE are actually the same
    phi = And(
        Symbol("F", BOOL),
        LE(Symbol("X", REAL), Symbol("Y", REAL)),
        LE(Symbol("Y", REAL), Symbol("X", REAL)),
        LE(Plus(Symbol("X", REAL), Times(Real(-1), Symbol("Y", REAL))), Real(0)),
        Symbol("Z", BOOL),
    )
    normal = formula.get_normalized(phi, converter)
    assert len(formula.get_atoms(normal)) == 4, "the normalized formula has 4 atoms"
    assert len(formula.get_atoms(normal)) < len(
        formula.get_atoms(phi)
    ), "equivalent atoms should be normalized into the same atom"
