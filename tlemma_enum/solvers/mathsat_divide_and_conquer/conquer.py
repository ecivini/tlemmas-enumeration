import mathsat
from pysmt.environment import Environment
from pysmt.fnode import FNode
from pysmt.formula import FormulaContextualizer
from pysmt.shortcuts import get_env
from pysmt.solvers.msat import MathSAT5Solver

from tlemma_enum.solvers.mathsat_utils import (
    AtomManager,
    EncodedClause,
    EncodedModel,
    allsat_callback_count,
    allsat_callback_store,
)
from tlemma_enum.util.pysmt import SuspendTypeChecking

_ATOM_MANAGER: AtomManager
_MSAT_PROJ_ATOMS: list[mathsat.msat_term]

_SOLVER: MathSAT5Solver
_STORE_MODELS: bool


def initialize_worker(
    phi: FNode,
    all_atoms: list[FNode],
    proj_atoms: list[int],
    tlemmas: list[EncodedClause],
    solver_options: dict[str, str],
    store_models: bool,
) -> None:
    global _ATOM_MANAGER, _MSAT_PROJ_ATOMS, _SOLVER, _STORE_MODELS
    _STORE_MODELS = store_models
    env: Environment = get_env()

    solver = env.factory.Solver("msat", solver_options=solver_options)
    _SOLVER = solver
    converter = solver.converter

    contextualizer = FormulaContextualizer()

    with SuspendTypeChecking():
        all_atoms = [contextualizer.walk(atom) for atom in all_atoms]
    _ATOM_MANAGER = AtomManager(all_atoms, converter, env)
    _MSAT_PROJ_ATOMS = [_ATOM_MANAGER.decode_literal_msat(atom) for atom in proj_atoms]

    phi = contextualizer.walk(phi)
    solver.add_assertion(phi)
    msat_env = solver.msat_env()
    for encoded_tlemma in tlemmas:
        mathsat.msat_assert_formula(msat_env, _ATOM_MANAGER.decode_clause_msat(encoded_tlemma))


def parallel_worker(model: list[int]) -> tuple[list[EncodedModel], int, list[EncodedClause]]:
    """Worker function for parallel all-smt extension

    Args:
        model: list of literal indexes

    Returns:
        tuple of found_models, found_models_count, found_tlemmas
    """
    global _ATOM_MANAGER, _MSAT_PROJ_ATOMS, _SOLVER, _STORE_MODELS

    solver = _SOLVER
    assert solver is not None
    msat_env = solver.msat_env()
    solver.push()

    atom_manager = _ATOM_MANAGER
    assert atom_manager is not None

    for lit in atom_manager.decode_model_msat(model):
        mathsat.msat_assert_formula(msat_env, lit)

    found_models: list[list[int]] = []
    found_models_count = 0
    if _STORE_MODELS:
        msat_models = []
        mathsat.msat_all_sat(
            solver.msat_env(),
            _MSAT_PROJ_ATOMS,
            callback=lambda model: allsat_callback_store(model, msat_models),
        )
        found_models = [atom_manager.encode_model_msat(model) for model in msat_models]
        found_models_count = len(found_models)
    else:
        models_count_l = [0]
        mathsat.msat_all_sat(
            solver.msat_env(),
            _MSAT_PROJ_ATOMS,
            callback=lambda _: allsat_callback_count(models_count_l),
        )
        found_models_count = models_count_l[0]

    found_tlemmas = [
        atom_manager.encode_clause_msat(lemma) for lemma in mathsat.msat_get_theory_lemmas(solver.msat_env())
    ]

    solver.pop()
    # solver.add_assertions(found_tlemmas)

    return found_models, found_models_count, found_tlemmas
