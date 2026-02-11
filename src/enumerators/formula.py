"""this module simplifies interactions with the pysmt library for handling SMT formulas"""

from typing import Collection, Iterable, List, Dict, Set
from pysmt.shortcuts import (
    And as _And,
    Or as _Or,
    BOOL as _BOOL,
    Not as _Not,
    read_smtlib as _read_smtlib,
    TRUE as _TRUE,
)
from pysmt.fnode import FNode

from enumerators.util.custom_exceptions import FormulaException
from enumerators.util.disjoint_set import DisjointSet
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
        other_phi = _read_smtlib(filename)
        return other_phi
    except Exception as _e:
        raise FormulaException("The input formula is not supported by the PYSMT package and cannot be read") from _e


def get_atoms(phi: FNode) -> List[FNode]:
    """Returns a list of all the atoms in the SMT formula

    Args:
        phi (FNode): a pysmt formula

    Returns:
        List[FNode]: the atoms in the formula
    """
    if not isinstance(phi, FNode):
        raise TypeError("Expected FNode found " + str(type(phi)))
    return list(phi.get_atoms())


def get_symbols(phi: FNode) -> List[FNode]:
    """returns all symbols in phi

    Args:
        phi (FNode): a pysmt formula

    Returns:
        List[FNode]: the symbols in the formula
    """
    if not isinstance(phi, FNode):
        raise TypeError("Expected FNode found " + str(type(phi)))
    return list(phi.get_free_variables())


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


def get_atom_partitioning(phi: FNode) -> List[Set[FNode]]:
    """partitions atoms into set

    phi must be a normalized formula or the partitioning may not be correct

    Args:
        phi (FNode): a pysmt formula
        skip_normalization (bool): if True, the formula is not normalized before partitioning

    Returns:
        List[Set[FNode]]: a list of sets of atoms that are in the same partition
    """
    atoms = get_atoms(phi)
    all_vars = phi.get_free_variables()
    if all_vars is None:
        # no free variables in the formula
        return [set(atoms)]

    # merge all variables that appear in the same atom
    disjoint_set_vars = DisjointSet(all_vars)
    # associate to each atom the first free variable that appears in it
    atoms_repr_vars: Dict[FNode, FNode] = {}
    theory_atoms = []
    for atom in atoms:
        atom_vars = list(atom.get_free_variables())

        # skip boolean atoms (that do not have free variables)
        if len(atom_vars) == 0:
            continue

        # add the atom to the theory_atoms list
        theory_atoms.append(atom)

        # associate to the atom a representative variable
        atoms_repr_vars[atom] = atom_vars[0]

        # join all variables that appear in the same atom
        for index, var_1 in enumerate(atom_vars):
            for var_2 in atom_vars[(index + 1) :]:
                disjoint_set_vars.union(var_1, var_2)
    # now all atoms have a find result on the disjoint set
    # which is disjoint_set_vars.find(atom.get_free_variables()[0])

    # merge atoms that share a variable
    disjoint_set_atoms = DisjointSet(theory_atoms)
    for index, atom_1 in enumerate(theory_atoms):
        # get repr for atom_1's first variable
        atom_1_repr = disjoint_set_vars.find(atoms_repr_vars[atom_1])
        for atom_2 in atoms[(index + 1) :]:
            # get repr for atom_2's first variable
            atom_2_repr = disjoint_set_vars.find(atoms_repr_vars[atom_2])
            # join atoms if they share the repr of disjoint_set_vars of their repr variable
            if atom_1_repr == atom_2_repr:
                disjoint_set_atoms.union(atom_1, atom_2)

    # get partitioning of theory atoms
    atoms_sets = list(disjoint_set_atoms.get_sets().values())

    # add singleton partition for all boolean atoms
    for atom in atoms:
        if atom not in theory_atoms:
            singleton_set = set()
            singleton_set.add(atom)
            atoms_sets.append(singleton_set)

    return atoms_sets


def get_true_given_atoms(atoms: Iterable[FNode]) -> FNode:
    """returns the formula that is True given the atoms

    Args:
        atoms (Iterable[FNode]): a set of pysmt atoms

    Returns:
        FNode: the formula that is always True given the atoms
    """
    if len(atoms) == 0:
        return _TRUE()
    big_and_items = []
    for atom in atoms:
        big_and_items.append(_Or(atom, _Not(atom)))
    return _And(*big_and_items)


def get_theory_atoms(atoms: Collection[FNode]) -> Collection[FNode]:
    return [atom for atom in atoms if not atom.is_symbol(_BOOL)]
