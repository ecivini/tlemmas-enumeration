import itertools as it
import time
from collections import defaultdict
from typing import Collection

from pysmt.fnode import FNode
from pysmt.shortcuts import And

from enumerators.formula import get_theory_atoms
from enumerators.solvers.solver import SMTEnumerator
from enumerators.util.pysmt import SuspendTypeChecking
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
) -> tuple[dict[FNode, list[FNode]], dict[FNode, list[FNode]]]:
    """
    Flattens a formula and groups conjunctive components that share free variables.

    Returns:
        dict[FNode, list[FNode]]: maps each component to the set of theory atoms it contains
        dict[FNode, list[FNode]]: maps each theory atom to the set of components containing it.
    """
    components = AndFlattener().flatten(phi)

    var_owner: dict[FNode, FNode] = {}
    uf = UnionFind()

    for c in components:
        for var in c.get_free_variables():
            owner = var_owner.get(var)
            if owner is None:
                var_owner[var] = c
            else:
                uf.union(c, owner)

    root_to_components: defaultdict[FNode, list[FNode]] = defaultdict(list)
    for component in components:
        root_to_components[uf.find(component)].append(component)

    component_to_atoms: dict[FNode, list[FNode]] = {}
    atom_to_components: defaultdict[FNode, list[FNode]] = defaultdict(list)
    for root_components in root_to_components.values():
        with SuspendTypeChecking():
            component = And(*root_components)
        atoms = get_theory_atoms(component.get_atoms())
        component_to_atoms[component] = atoms

        for atom in atoms:
            atom_to_components[atom].append(component)

    return component_to_atoms, atom_to_components


def get_partition_relevant_formula(
    component_to_atoms: dict[FNode, list[FNode]],
    atom_to_components: dict[FNode, list[FNode]],
    partition_atoms: set[FNode],
) -> tuple[FNode, set[FNode]]:
    """Construct a partition-relevant formula."""
    touched_components = {comp for atom in partition_atoms for comp in atom_to_components[atom]}
    n_touched, n_components = len(touched_components), len(component_to_atoms)
    print(f"Touched components: {n_touched}/{n_components}")
    with SuspendTypeChecking():
        psi = And(*touched_components) if touched_components else And()
    psi_atoms = set().union(*(component_to_atoms[c] for c in touched_components))
    return psi, psi_atoms


def get_partition_relevant_lemmas(
    tlemmas: list[FNode],
    psi_atoms: set[FNode],
) -> list[FNode]:
    """Filter lemmas based on shared atoms with current formula psi."""
    relevant_lemmas = [lemma for lemma in tlemmas if not psi_atoms.isdisjoint(lemma.get_atoms())]
    n_relevant_lemmas, n_lemmas = len(relevant_lemmas), len(tlemmas)
    print(f"Using {n_relevant_lemmas}/{n_lemmas} relevant lemmas for this partition.")
    return relevant_lemmas


class WithPartitioningWrapper(SMTEnumerator):
    def __init__(
        self,
        base_solver: SMTEnumerator,
        partition_on_formula_components: bool = True,
        share_tlemmas_between_partitions: bool = False,
        computation_logger: dict | None = None,
    ):
        super().__init__(computation_logger)
        self._base_solver = base_solver
        self._partition_on_formula_components = partition_on_formula_components
        self._share_tlemmas_between_partitions = share_tlemmas_between_partitions
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
        with self._timer.track_time("Partitioning time"):
            partitions = partition_atoms(atoms)

            # partition the formula based on the And-conjoined components
            component_to_atoms, atom_to_components = {}, {}
            if self._partition_on_formula_components:
                component_to_atoms, atom_to_components = get_conjoined_components(phi)

        self.log("Number of partitions", len(partitions))

        # Solve each partition separately
        overall_result = True
        partitions_loggers: list[dict] = []
        for part_atoms in sorted(partitions, key=lambda x: len(x)):
            iter_start = time.perf_counter_ns()
            print("Solving partition with {} atoms...".format(len(part_atoms)))
            self._base_solver.reset()
            if self.computation_logger is not None:
                partition_logger: dict = {}
                self._base_solver.computation_logger = partition_logger
                partitions_loggers.append(partition_logger)

            psi = phi
            psi_atoms = None
            if self._partition_on_formula_components:
                psi, psi_atoms = get_partition_relevant_formula(component_to_atoms, atom_to_components, part_atoms)

            if not self._share_tlemmas_between_partitions:
                relevant_lemmas = []
            elif self._partition_on_formula_components:
                assert psi_atoms is not None
                relevant_lemmas = get_partition_relevant_lemmas(self._tlemmas, psi_atoms)
            else:
                relevant_lemmas = self._tlemmas

            with SuspendTypeChecking():
                psi = And(psi, *relevant_lemmas)
            result = self._base_solver.check_all_sat(psi, list(part_atoms), store_models)
            if not result:
                overall_result = False
            self._tlemmas.extend(self._base_solver.get_theory_lemmas())
            self._models_count += self._base_solver.get_models_count()
            if store_models:
                self._models.extend(self._base_solver.get_models())
            print("Partition solved in {:.2f} seconds.".format((time.perf_counter_ns() - iter_start) / 1e9))
        if self.computation_logger is not None:
            # Restore base solver's computation logger after changing it for each partition
            self._base_solver.computation_logger = self.computation_logger
            self.log("Partitions", partitions_loggers)
            self.log("Total models", sum(plogger["Total models"] for plogger in partitions_loggers))
            self.log("Lemmas", sum(plogger["Lemmas"] for plogger in partitions_loggers))
        return overall_result

    def get_theory_lemmas(self) -> list[FNode]:
        return self._tlemmas

    def get_converter(self) -> object:
        return self._base_solver.get_converter()

    def get_models(self) -> list:
        return self._models

    def get_models_count(self) -> int:
        return self._models_count
