from collections import defaultdict
from pysmt.fnode import FNode


def rank_atoms_by_hub_centrality(atoms: list[FNode]) -> list[FNode]:
    var_freq = {}
    for atom in atoms:
        for var in atom.get_free_variables():
            var_freq[var] = var_freq.get(var, 0) + 1

    def score(atom):
        return sum(var_freq[v] for v in atom.get_free_variables())

    return sorted(atoms, key=score, reverse=True)


def rank_atoms_by_degree(atoms):
    var_to_atoms = defaultdict(set)
    for i, atom in enumerate(atoms):
        for var in atom.get_free_variables():
            var_to_atoms[var].add(i)

    atom_degrees = []
    for i, atom in enumerate(atoms):
        neighbors = set()
        for var in atom.get_free_variables():
            neighbors.update(var_to_atoms[var])

        degree = len(neighbors) - 1
        atom_degrees.append((degree, atom))

    return [atom for _, atom in sorted(atom_degrees, key=lambda x: x[0], reverse=True)]
