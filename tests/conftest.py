import pysmt.environment
from pysmt.fnode import FNode
import pytest
from pysmt.shortcuts import REAL, Symbol
from pysmt.typing import ArrayType, BOOL, INT, BV8

from enumerators.formula import read_phi
from enumerators.solvers import (
    SMTEnumerator,
    MathSATTotalEnumerator,
    DivideByPartialAllSMTStrategy,
    DivideByProjectedEnumerationStrategy,
    MathSATDivideAndConquerEnumerator,
    WithPartitioningWrapper,
)


def pytest_runtest_setup():
    env: pysmt.environment.Environment = pysmt.environment.reset_env()
    env.enable_infix_notation = True


# fmt: off
SOLVERS = [
    ("total", MathSATTotalEnumerator, {"project_on_theory_atoms": False}),
    ("total-project", MathSATTotalEnumerator, {"project_on_theory_atoms": True}),
    ("dc-1-div_strategy-partial", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": False, "parallel_procs": 1, "divide_strategy": DivideByPartialAllSMTStrategy}),
    ("dc-1-div_strategy-project", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": False, "parallel_procs": 1, "divide_strategy": DivideByProjectedEnumerationStrategy}),
    ("dc-project-1-div_strategy-partial", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": True, "parallel_procs": 1, "divide_strategy": DivideByPartialAllSMTStrategy}),
    ("dc-project-1-div_strategy-project", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": True, "parallel_procs": 1, "divide_strategy": DivideByProjectedEnumerationStrategy}),
    ("dc-8-div_strategy-partial", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": False, "parallel_procs": 8, "divide_strategy": DivideByPartialAllSMTStrategy}),
    ("dc-8-div_strategy-project", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": False, "parallel_procs": 8, "divide_strategy": DivideByProjectedEnumerationStrategy}),
    ("dc-project-8-div_strategy-partial", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": True, "parallel_procs": 8, "divide_strategy": DivideByPartialAllSMTStrategy}),
    ("dc-project-8-div_strategy-project", MathSATDivideAndConquerEnumerator, {"project_on_theory_atoms": True, "parallel_procs": 8, "divide_strategy": DivideByProjectedEnumerationStrategy}),
]
# fmt: on


@pytest.fixture(params=SOLVERS, ids=lambda s: s[0])
def solver(request: pytest.FixtureRequest) -> SMTEnumerator:
    _, solver_cls, params = request.param
    return solver_cls(**params)


@pytest.fixture(
    params=["raw", "partitioned", "partitioned-on-components", "partitioned-on-components-no-tlemmas-share"],
    ids=["mode:raw", "mode:part", "mode:part-comp", "mode:part-comp-noshare"],
)
def wsolver(solver: SMTEnumerator, request: pytest.FixtureRequest) -> SMTEnumerator:
    if request.param == "raw":
        return solver
    elif request.param == "partitioned":
        return WithPartitioningWrapper(
            base_solver=solver, partition_on_formula_components=False, share_tlemmas_between_partitions=True
        )
    elif request.param == "partitioned-on-components":
        return WithPartitioningWrapper(
            base_solver=solver, partition_on_formula_components=True, share_tlemmas_between_partitions=True
        )
    elif request.param == "partitioned-on-components-no-tlemmas-share":
        return WithPartitioningWrapper(
            base_solver=solver, partition_on_formula_components=True, share_tlemmas_between_partitions=False
        )
    else:
        raise ValueError(f"Unknown partitioning mode: {request.param}")


@pytest.fixture
def solver_info(wsolver: SMTEnumerator) -> tuple[SMTEnumerator, bool, bool]:
    return (
        wsolver,
        getattr(wsolver, "_project_on_theory_atoms", False),
        isinstance(wsolver, WithPartitioningWrapper),
    )


# ---- Real variables ----
@pytest.fixture
def w() -> FNode:
    return Symbol("w", REAL)


@pytest.fixture
def x() -> FNode:
    return Symbol("x", REAL)


@pytest.fixture
def y() -> FNode:
    return Symbol("y", REAL)


@pytest.fixture
def z() -> FNode:
    return Symbol("z", REAL)


# ---- Integer variables ----


@pytest.fixture
def i() -> FNode:
    return Symbol("i", INT)


@pytest.fixture
def j() -> FNode:
    return Symbol("j", INT)


@pytest.fixture
def k() -> FNode:
    return Symbol("k", INT)


# ---- Boolean variables ----


@pytest.fixture
def a() -> FNode:
    return Symbol("a", BOOL)


@pytest.fixture
def b() -> FNode:
    return Symbol("b", BOOL)


@pytest.fixture
def c() -> FNode:
    return Symbol("c", BOOL)


# ---- BV variables ----
@pytest.fixture
def bv1() -> FNode:
    return Symbol("bv1", BV8)


@pytest.fixture
def bv2() -> FNode:
    return Symbol("bv2", BV8)


# ---- Array variables ----


@pytest.fixture
def array1() -> FNode:
    return Symbol("arr1", ArrayType(INT, INT))


@pytest.fixture
def array2() -> FNode:
    return Symbol("arr2", ArrayType(INT, INT))


@pytest.fixture
def bool_vars(a: FNode, b: FNode, c: FNode) -> dict[str, FNode]:
    return {"A": a, "B": b, "C": c}


@pytest.fixture
def real_vars(w: FNode, x: FNode, y: FNode, z: FNode) -> dict[str, FNode]:
    return {"x": x, "y": y, "z": z, "w": w}


@pytest.fixture
def int_vars(i: FNode, j: FNode, k: FNode) -> dict[str, FNode]:
    return {"i": i, "j": j, "k": k}


@pytest.fixture
def bv_vars(bv1: FNode, bv2: FNode) -> dict[str, FNode]:
    return {"bv1": bv1, "bv2": bv2}


@pytest.fixture
def array_vars(array1: FNode, array2: FNode) -> dict[str, FNode]:
    return {"arr1": array1, "arr2": array2}


@pytest.fixture
def all_vars(
    bool_vars: dict[str, FNode],
    real_vars: dict[str, FNode],
    int_vars: dict[str, FNode],
    bv_vars: dict[str, FNode],
    array_vars: dict[str, FNode],
) -> dict[str, FNode]:
    all_vars = {}
    all_vars.update(bool_vars)
    all_vars.update(real_vars)
    all_vars.update(int_vars)
    all_vars.update(bv_vars)
    all_vars.update(array_vars)
    return all_vars


@pytest.fixture
def sat_formula(x: FNode, y: FNode, z: FNode) -> FNode:
    return (x < y) | (y < z) | (z < x) | x.Equals(5)


@pytest.fixture
def unsat_formula(x: FNode, y: FNode, z: FNode) -> FNode:
    return (x < y) & (y < z) & (z < x)


@pytest.fixture
def prop_unsat_formula(x: FNode, y: FNode) -> FNode:
    return (x < y) & ~(x < y)


@pytest.fixture
def valid_formula(x: FNode) -> FNode:
    return (x < 1) | ~(x < 0)


@pytest.fixture
def prop_valid_formula(x: FNode, y: FNode) -> FNode:
    return (x < y) | ~(x < y)


@pytest.fixture
def rangen_formula() -> FNode:
    """Rangen formula fixture"""
    return read_phi("./tests/items/rng.smt")


@pytest.fixture(params=["sat_formula", "unsat_formula", "valid_formula", "rangen_formula"])
def any_formula(request: pytest.FixtureRequest) -> FNode:
    """Return all formula fixtures one by one via parametrization"""
    return request.getfixturevalue(request.param)
