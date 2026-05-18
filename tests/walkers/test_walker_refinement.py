from pysmt.shortcuts import And, Equals, Iff, Int, Or, Symbol, is_valid

from enumerators.walkers.walker_bool_abstraction import BooleanAbstractionWalker
from enumerators.walkers.walker_refinement import RefinementWalker


def test_boolean_abstraction_and_refinement_round_trip():
    ten = Int(10)
    zero = Int(0)
    a = Symbol("a", ten.get_type())
    b = Symbol("b", ten.get_type())

    phi = And(
        Or(Equals(a, ten), Equals(b, zero)),
        Equals(a, zero),
    )

    abstr_walker = BooleanAbstractionWalker()
    abstr_phi = abstr_walker.walk(phi)

    refinement_walker = RefinementWalker(abstraction=abstr_walker.abstraction)
    refined_phi = refinement_walker.walk(abstr_phi)

    assert is_valid(Iff(phi, refined_phi)), (
        "Refinement should recover the original formula"
    )
