from pysmt.fnode import FNode
from pysmt.shortcuts import is_valid
from pysmt.typing import BOOL

from tlemma_enum.walkers.walker_bool_abstraction import BooleanAbstractionWalker
from tlemma_enum.walkers.walker_refinement import RefinementWalker


def test_bool_abstraction_walker(i: FNode, j: FNode, k: FNode) -> None:
    formula: FNode = (i.Equals(10).Implies(j.Equals(0)) | i.Equals(0).Implies(j.Equals(10))) & (
        j.Equals(10).Implies(k.Equals(0)) | j.Equals(0).Implies(k.Equals(10))
    )

    abswalker = BooleanAbstractionWalker()
    abstracted_formula = abswalker.abstract(formula)

    assert len(abswalker.abstraction) == 6
    assert abstracted_formula == formula.substitute(abswalker.abstraction)
    assert all(atom.is_symbol(BOOL) for atom in abstracted_formula.get_atoms())


def test_bool_abstraction_preserves_boolean_atoms(a: FNode, x: FNode, y: FNode) -> None:
    formula: FNode = a & (x.Equals(1) | y.Equals(2))

    abswalker = BooleanAbstractionWalker()
    abstracted_formula = abswalker.abstract(formula)

    expected_abstracted = formula.substitute(abswalker.abstraction)
    assert a in abstracted_formula.get_atoms()
    assert is_valid(abstracted_formula.Iff(expected_abstracted))


def test_boolean_abstraction_and_refinement_round_trip(x: FNode, y: FNode, a: FNode) -> None:
    phi: FNode = a | ((x.Equals(10) | y.Equals(0)) & x.Equals(0))
    phi_atoms = phi.get_atoms()

    abstr_walker = BooleanAbstractionWalker()
    abstr_phi: FNode = abstr_walker.abstract(phi)
    abstraction = abstr_walker.abstraction

    abstr_phi_atoms = abstr_phi.get_atoms()
    assert len(abstraction) == 3
    assert all(atom.is_symbol(BOOL) for atom in abstr_phi_atoms)
    assert all(abstr.is_symbol(BOOL) for abstr in abstraction.values())

    bool_atoms = {atom for atom in phi_atoms if atom.is_symbol(BOOL)}
    assert bool_atoms <= abstr_phi_atoms

    refinement_walker = RefinementWalker(abstraction=abstraction)
    refined_phi = refinement_walker.refine(abstr_phi)

    assert phi == refined_phi, "Refinement should recover the original formula"
