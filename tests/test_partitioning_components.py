from dataclasses import dataclass
from typing import Callable

import pytest
from pysmt.fnode import FNode

from enumerators.formula import get_normalized, get_theory_atoms
from enumerators.solvers import MathSATTotalEnumerator, WithPartitioningWrapper
from enumerators.solvers.with_partitioning import (
    get_conjoined_components,
    get_partition_relevant_formula,
    partition_atoms,
)


@dataclass
class PartitionCase:
    name: str
    formula_builder: Callable[[dict[str, FNode]], FNode]
    expected_component_atom_sizes: tuple[int, ...]
    expected_partition_atom_sizes: tuple[int, ...]
    expected_partition_psi_atom_sizes: tuple[int, ...]
    expected_models_count: tuple[int, ...]


PARTITION_CASES = [
    PartitionCase(
        "one-component-overcount",
        lambda s: ((s["x"] <= 0) | (s["x"] <= 1)) & (s["y"] <= 0),
        (2, 1),
        (2, 1),
        (2, 1),
        (2, 1),
    ),
    PartitionCase(
        "two-component-overcount",
        lambda s: ((s["x"] <= 0) | (s["x"] <= 1)) & ((s["x"] <= 0) | (s["y"] <= 0)),
        (3,),
        (2, 1),
        (3, 3),
        (2, 2),
    ),
    PartitionCase(
        "shared-x-y-components",
        lambda s: ((s["x"] <= 0) | (s["y"] <= 0)) & ((s["x"] <= 1) | (s["y"] <= 1)),
        (4,),
        (2, 2),
        (4, 4),
        (3, 3),
    ),
    PartitionCase(
        "shared-x-y-components-unsat-prop",
        lambda s: ((s["x"] <= 0) | (s["y"] <= 0)) & ~(s["x"] <= 0),
        (2,),
        (1, 1),
        (2, 2),
        (1, 1),
    ),
    PartitionCase(
        "shared-x-y-components-unsat-theory",
        lambda s: ((s["x"] <= 0) | (s["y"] <= 0)) & ~(s["x"] <= 1),
        (3,),
        (2, 1),
        (3, 3),
        (1, 1),
    ),
    PartitionCase(
        "bool-bridge-components",
        lambda s: (s["A"] | (s["x"] <= 0)) & (~s["A"] | (s["y"] <= 0)),
        (2,),
        (1, 1),
        (2, 2),
        (2, 2),
    ),
    PartitionCase(
        "bool-chain-components",
        lambda s: (s["A"] | (s["x"] <= 0)) & (~s["A"] | (s["y"] <= 0)) & (s["B"] | (s["y"] <= 1)),
        (3,),
        (2, 1),
        (3, 3),
        (3, 2),
    ),
    PartitionCase(
        "bool-chain-components-constrained",
        lambda s: (s["A"] | (s["x"] <= 0)) & (~s["A"] | (s["y"] <= 0)) & (s["B"] | ~(s["y"] <= 1)) & ~s["B"],
        (3,),
        (2, 1),
        (3, 3),
        (1, 1),
    ),
]


@pytest.fixture(params=PARTITION_CASES, ids=lambda tc: tc.name)
def partition_case(request: pytest.FixtureRequest, all_vars: dict[str, FNode]) -> tuple[FNode, PartitionCase]:
    tc: PartitionCase = request.param
    return tc.formula_builder(all_vars), tc


@pytest.fixture(params=[False, True], ids=["no-share-tlemmas", "share-tlemmas"])
def share_tlemmas_between_partitions(request: pytest.FixtureRequest) -> bool:
    return request.param


def test_component_partition_structure(partition_case: tuple[FNode, PartitionCase]) -> None:
    phi, tc = partition_case

    component_to_atoms, atom_to_components = get_conjoined_components(phi)
    partitions = partition_atoms(get_theory_atoms(phi.get_atoms()))

    assert sorted(len(atoms) for atoms in component_to_atoms.values()) == sorted(tc.expected_component_atom_sizes)
    assert sorted(len(partition) for partition in partitions) == sorted(tc.expected_partition_atom_sizes)

    psi_atom_sizes = []
    for partition in partitions:
        psi, psi_atoms = get_partition_relevant_formula(component_to_atoms, atom_to_components, partition)
        assert set(get_theory_atoms(psi.get_atoms())) == psi_atoms
        psi_atom_sizes.append(len(psi_atoms))

    assert sorted(psi_atom_sizes) == sorted(tc.expected_partition_psi_atom_sizes)


def test_partitioned_component_count(
    partition_case: tuple[FNode, PartitionCase],
    share_tlemmas_between_partitions: bool,
) -> None:
    phi, tc = partition_case

    computation_logger = {}
    partitioned_solver = WithPartitioningWrapper(
        base_solver=MathSATTotalEnumerator(),
        partition_on_formula_components=True,
        share_tlemmas_between_partitions=share_tlemmas_between_partitions,
        computation_logger=computation_logger,
    )

    phi = get_normalized(phi, partitioned_solver.get_converter())
    atoms = list(phi.get_atoms())

    assert partitioned_solver.check_all_sat(phi, atoms=atoms, store_models=True)
    assert partitioned_solver.get_models_count() == sum(tc.expected_models_count), "Logger: {}, Models: {}".format(
        computation_logger, partitioned_solver.get_models()
    )
