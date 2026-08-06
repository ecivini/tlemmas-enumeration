from pysmt.fnode import FNode


def rank_atoms_by_hub_centrality(atoms: list[FNode]) -> list[FNode]:
    var_freq = {}
    for atom in atoms:
        for var in atom.get_free_variables():
            var_freq[var] = var_freq.get(var, 0) + 1

    def score(atom):
        return sum(var_freq[v] for v in atom.get_free_variables())

    return sorted(atoms, key=score, reverse=True)
