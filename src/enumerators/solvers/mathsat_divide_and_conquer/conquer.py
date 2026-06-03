import mathsat
from pysmt.environment import Environment
from pysmt.fnode import FNode
from pysmt.formula import FormulaContextualizer
from pysmt.shortcuts import get_env
from pysmt.solvers.msat import MathSAT5Solver

from enumerators.solvers.mathsat_utils import (
    AtomManager,
    EncodedClause,
    EncodedModel,
    allsat_callback_count,
    allsat_callback_store,
    get_converted_atoms,
)
from enumerators.util.pysmt import SuspendNodeStoring, SuspendTypeChecking
from enumerators.walkers.normalizer import NormalizerWalker


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
    normalizer = NormalizerWalker(converter)

    all_atoms = [normalizer.normalize(contextualizer.walk(atom)) for atom in all_atoms]
    _ATOM_MANAGER = AtomManager(all_atoms, env)
    _MSAT_PROJ_ATOMS = get_converted_atoms([_ATOM_MANAGER.decode_literal(atom) for atom in proj_atoms], converter)

    phi = contextualizer.walk(phi)
    solver.add_assertion(phi)
    for encoded_tlemma in tlemmas:
        solver.add_assertion(_ATOM_MANAGER.decode_clause(encoded_tlemma))


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
    converter = solver.converter
    solver.push()

    atom_manager = _ATOM_MANAGER
    assert atom_manager is not None

    solver.add_assertions(atom_manager.decode_model(model))

    found_models: list[list[int]] = []
    found_models_count = 0
    if _STORE_MODELS:
        pysmt_models = []
        mathsat.msat_all_sat(
            solver.msat_env(),
            _MSAT_PROJ_ATOMS,
            callback=lambda model: allsat_callback_store(model, converter, pysmt_models),
        )
        found_models = [atom_manager.encode_model(model) for model in pysmt_models]
        found_models_count = len(found_models)
    else:
        models_count_l = [0]
        mathsat.msat_all_sat(
            solver.msat_env(),
            _MSAT_PROJ_ATOMS,
            callback=lambda _: allsat_callback_count(models_count_l),
        )
        found_models_count = models_count_l[0]

    with SuspendTypeChecking(), SuspendNodeStoring():
        found_tlemmas = [
            atom_manager.encode_clause(converter.back(lemma))
            for lemma in mathsat.msat_get_theory_lemmas(solver.msat_env())
        ]

    solver.pop()
    # solver.add_assertions(found_tlemmas)

    return found_models, found_models_count, found_tlemmas
