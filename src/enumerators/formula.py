"""this module simplifies interactions with the pysmt library for handling SMT formulas"""

from typing import Collection
from pysmt.fnode import FNode
from pysmt.typing import BOOL

from enumerators.util.pysmt import SuspendTypeChecking
from enumerators.walkers.normalizer import NormalizerWalker


def get_normalized(phi: FNode, converter) -> FNode:
    """Returns a normalized version of phi

    Args:
        phi (FNode): a pysmt formula

    Returns:
        FNode: the provided formula normalized according to the converter
    """
    walker = NormalizerWalker(converter)
    with SuspendTypeChecking():
        return walker.normalize(phi)


def get_theory_atoms(atoms: Collection[FNode]) -> list[FNode]:
    return [atom for atom in atoms if not atom.is_symbol(BOOL)]


def is_atom(atom: FNode) -> bool:
    return atom.is_symbol(BOOL) or atom.is_theory_relation() or atom.is_bool_constant()


def is_literal(literal: FNode) -> bool:
    return is_atom(literal) or (literal.is_not() and is_atom(literal.arg(0)))


def is_clause(phi: FNode) -> bool:
    return is_literal(phi) or (phi.is_or() and all(is_clause(a) for a in phi.args()))
