"""this module simplifies interactions with the pysmt library for handling SMT formulas"""

from typing import Collection, cast
from pysmt.shortcuts import (
    BOOL as _BOOL,
    read_smtlib,
)
from pysmt.fnode import FNode

from enumerators.util.custom_exceptions import FormulaException
from enumerators.walkers.normalizer import NormalizerWalker


def read_phi(filename: str) -> FNode:
    """Reads the SMT formula from a file and returns the corresponding root FNode

    Args:
        filename (str): the name of the file

    Returns:
        FNode: the pysmt formula read from the file
    """
    # pylint: disable=unused-argument
    if not isinstance(filename, str):
        raise TypeError("Expected str found " + str(type(filename)))
    try:
        other_phi = cast(FNode, read_smtlib(filename))
        return other_phi
    except Exception as _e:
        raise FormulaException("The input formula is not supported by the PYSMT package and cannot be read") from _e


def get_normalized(phi: FNode, converter) -> FNode:
    """Returns a normalized version of phi

    Args:
        phi (FNode): a pysmt formula

    Returns:
        FNode: the provided formula normalized according to the converter
    """
    if not isinstance(phi, FNode):
        raise TypeError("Expected FNode found " + str(type(phi)))
    walker = NormalizerWalker(converter)
    return walker.walk(phi)


def get_theory_atoms(atoms: Collection[FNode]) -> list[FNode]:
    return [atom for atom in atoms if not atom.is_symbol(_BOOL)]
