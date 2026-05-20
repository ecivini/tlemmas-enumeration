from pysmt.fnode import FNode
from pysmt.typing import BOOL

from enumerators.walkers.walker_bool_abstraction import BooleanAbstractionWalker
from enumerators.walkers.walker_refinement import RefinementWalker


def test_boolean_abstraction_and_refinement_round_trip(x, y, a):
    phi = a | (x.Equals(10) | y.Equals(0)) & x.Equals(0)
    phi_atoms: set[FNode] = phi.get_atoms()

    abstr_walker = BooleanAbstractionWalker()
    abstr_phi: FNode = abstr_walker.abstract(phi)
    abstraction = abstr_walker.abstraction

    abstr_phi_atoms: set[FNode] = abstr_phi.get_atoms()
    assert all(atom.is_symbol(BOOL) for atom in abstr_phi_atoms)

    assert all(abstr.is_symbol(BOOL) for abstr in abstraction.values())

    assert all(atom in abstr_phi_atoms for atom in phi_atoms if atom.is_symbol(BOOL))

    refinement_walker = RefinementWalker(abstraction=abstraction)
    refined_phi = refinement_walker.refine(abstr_phi)

    assert phi == refined_phi, "Refinement should recover the original formula"
