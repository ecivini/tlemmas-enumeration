from pysmt.fnode import FNode
from pysmt.shortcuts import And, Equals, Or, Real, Symbol
from pysmt.typing import BOOL, REAL

from enumerators.walkers.walker_bool_abstraction import BooleanAbstractionWalker
from enumerators.walkers.walker_refinement import RefinementWalker


def test_boolean_abstraction_and_refinement_round_trip():
    ten = Real(10)
    zero = Real(0)
    a = Symbol("a", REAL)
    b = Symbol("b", REAL)
    c = Symbol("C", BOOL)

    phi = Or(
        c,
        And(
            Or(Equals(a, ten), Equals(b, zero)),
            Equals(a, zero),
        ),
    )
    phi_atoms: set[FNode] = phi.get_atoms()

    abstr_walker = BooleanAbstractionWalker()
    abstr_phi: FNode = abstr_walker.walk(phi)
    abstraction = abstr_walker.abstraction

    abstr_phi_atoms: set[FNode] = abstr_phi.get_atoms()
    assert all(atom.is_symbol(BOOL) for atom in abstr_phi_atoms)

    assert all(abstr.is_symbol(BOOL) for abstr in abstraction.values())

    assert all(atom in abstr_phi_atoms for atom in phi_atoms if atom.is_symbol(BOOL))

    refinement_walker = RefinementWalker(abstraction=abstraction)
    refined_phi = refinement_walker.walk(abstr_phi)

    assert phi == refined_phi, "Refinement should recover the original formula"
