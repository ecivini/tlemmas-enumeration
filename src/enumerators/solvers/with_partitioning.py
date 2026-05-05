import itertools as it
import time
from collections import defaultdict
from typing import Collection, List

from pysmt.fnode import FNode
from pysmt.shortcuts import And

from enumerators.formula import get_theory_atoms
from enumerators.solvers.solver import SMTEnumerator
from enumerators.walkers.and_flattener import AndFlattener


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, item):
        if item not in self.parent:
            self.parent[item] = item
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, item1, item2):
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 != root2:
            self.parent[root2] = root1


def partition_atoms(atoms: Collection[FNode]) -> list[set[FNode]]:
    uf = UnionFind()
    all_vars = set()
    for atom in atoms:
        theory_vars = [v for v in atom.get_free_variables()]
        all_vars.update(theory_vars)
        for v1, v2 in it.combinations(theory_vars, 2):
            uf.union(v1, v2)

    partitions = {}
    for atom in atoms:
        root = uf.find(next(iter(atom.get_free_variables())))
        if root not in partitions:
            partitions[root] = []
        partitions[root].append(atom)
    return list(map(lambda x: set(x), partitions.values()))


def get_conjoined_components(
    phi: FNode,
) -> tuple[dict[FNode, frozenset[FNode]], dict[FNode, set[FNode]]]:
    """
    Flattens a formula and maps components to their atoms, and atoms to their components.
    """
    components = AndFlattener().flatten(phi)

    component_to_atoms: dict[FNode, frozenset[FNode]] = {}
    atom_to_components: defaultdict[FNode, set[FNode]] = defaultdict(set)

    for c in components:
        # Precompute the theory atoms for this component once
        atoms = frozenset(get_theory_atoms(c.get_atoms()))
        component_to_atoms[c] = atoms

        for atom in atoms:
            atom_to_components[atom].add(c)

    return component_to_atoms, atom_to_components


def get_partition_relevant_formula_and_lemmas(
    component_to_atoms: dict[FNode, frozenset[FNode]],
    atom_to_components: dict[FNode, set[FNode]],
    part_atoms: set[FNode],
    tlemmas: list[FNode],
) -> tuple[FNode, list[FNode]]:
    """
    Constructs a partition-relevant formula and filters lemmas based on shared atoms.
    """
    touched_components = {
        comp for atom in part_atoms for comp in atom_to_components[atom]
    }
    n_touched, n_components = len(touched_components), len(component_to_atoms)
    print(f"Touched components: {n_touched}/{n_components}")

    psi = And(*touched_components) if touched_components else And()
    if n_touched == n_components:
        return psi, tlemmas

    psi_atoms = set().union(*(component_to_atoms[c] for c in touched_components))
    relevant_lemmas = [
        lemma for lemma in tlemmas if not psi_atoms.isdisjoint(lemma.get_atoms())
    ]
    n_relevant_lemmas, n_lemmas = len(relevant_lemmas), len(tlemmas)
    print(f"Using {n_relevant_lemmas}/{n_lemmas} relevant lemmas for this partition.")

    return psi, relevant_lemmas


class WithPartitioningWrapper(SMTEnumerator):
    def __init__(
        self,
        base_solver: SMTEnumerator,
        partition_on_formula_components: bool = False,
        computation_logger: dict | None = None,
    ):
        super().__init__(computation_logger)
        self._base_solver = base_solver
        self._partition_on_formula_components = partition_on_formula_components
        self._project_on_theory_atoms = True
        self._tlemmas = []
        self._models = []
        self._models_count = 0

    def reset(self):
        self._tlemmas = []
        self._models = []
        self._models_count = 0
        self._base_solver.reset()

    def check_all_sat(self, phi, atoms=None, store_models=False) -> bool:
        self.reset()
        atoms = phi.get_atoms() if atoms is None else atoms
        atoms = get_theory_atoms(atoms)
        # Partition atoms based on their variables
        start_time = time.time()
        partitions = partition_atoms(atoms)

        # partition the formula based on the And-conjoined components
        component_to_atoms, atom_to_components = {}, {}
        if self._partition_on_formula_components:
            component_to_atoms, atom_to_components = get_conjoined_components(phi)

        end_time = time.time()
        if self._computation_logger is not None:
            self._computation_logger["Partitioning time"] = end_time - start_time
            self._computation_logger["Number of partitions"] = len(partitions)

        # Solve each partition separately
        overall_result = True
        for part_atoms in sorted(partitions, key=lambda x: len(x)):
            start_time = time.time()
            print("Solving partition with {} atoms...".format(len(part_atoms)))
            self._base_solver.reset()
            psi = phi
            relevant_lemmas = self._tlemmas
            if self._partition_on_formula_components:
                psi, relevant_lemmas = get_partition_relevant_formula_and_lemmas(
                    component_to_atoms,
                    atom_to_components,
                    part_atoms,
                    self._tlemmas,
                )
            result = self._base_solver.check_all_sat(
                And(psi, *relevant_lemmas), list(part_atoms), store_models
            )
            if not result:
                overall_result = False
            self._tlemmas.extend(self._base_solver.get_theory_lemmas())
            self._models_count += self._base_solver.get_models_count()
            if store_models:
                self._models.extend(self._base_solver.get_models())
            end_time = time.time()
            print("Partition solved in {:.2f} seconds.".format(end_time - start_time))
        return overall_result

    def get_theory_lemmas(self) -> List[FNode]:
        return self._tlemmas

    def get_converter(self) -> object:
        return self._base_solver.get_converter()

    def get_models(self) -> List:
        return self._models

    def get_models_count(self) -> int:
        return self._models_count
