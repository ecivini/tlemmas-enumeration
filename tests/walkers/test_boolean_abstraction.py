from pysmt.fnode import FNode
from pysmt.shortcuts import is_valid
from enumerators.walkers.walker_bool_abstraction import BooleanAbstractionWalker


def test_bool_abstraction_walker(i, j, k):
    or_1 = i.Equals(10).Implies(j.Equals(0)) | i.Equals(0).Implies(j.Equals(10))
    or_2 = j.Equals(10).Implies(k.Equals(0)) | j.Equals(0).Implies(k.Equals(10))

    formula: FNode = or_1 & or_2

    abswalker = BooleanAbstractionWalker()
    abstracted_formula = abswalker.abstract(formula)

    assert len(abswalker.abstraction) == 6, "There should be 6 abstracted atoms"

    expected_abstracted = formula.substitute(abswalker.abstraction)
    assert is_valid(abstracted_formula.Iff(expected_abstracted)), "Abstracted formula does not match expected structure"
