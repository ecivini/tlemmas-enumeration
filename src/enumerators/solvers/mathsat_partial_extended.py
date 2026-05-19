"""this module handles interactions with the mathsat solver"""

import multiprocessing
import time
from typing import Protocol, cast

import mathsat
from allsat_cnf.polarity_cnfizer import PolarityCNFizer
from pysmt.environment import Environment
from pysmt.fnode import FNode
from pysmt.formula import FormulaContextualizer
from pysmt.shortcuts import Solver, get_env
from pysmt.solvers.msat import MathSAT5Solver

from enumerators.constants import SAT, UNSAT
from enumerators.formula import get_theory_atoms
from enumerators.solvers.solver import SMTEnumerator
from enumerators.walkers.normalizer import NormalizerWalker
from .mathsat_utils import (
    MSAT_PARTIAL_ENUM_OPTIONS,
    MSAT_TOTAL_ENUM_OPTIONS,
    AtomManager,
    EncodedClause,
    EncodedModel,
    allsat_callback_count,
    allsat_callback_store,
)


_ATOM_MANAGER: AtomManager | None = None
_MSAT_ATOMS = []

_SOLVER: MathSAT5Solver | None = None
_STORE_MODELS: bool = False


def _initialize_worker(
    phi: FNode,
    proj_atoms: list[FNode],
    tlemmas: list[tuple[list[int], list[str]]],
    solver_options: dict[str, str],
    store_models: bool,
) -> None:
    global _ATOM_MANAGER, _MSAT_ATOMS, _SOLVER, _STORE_MODELS
    _STORE_MODELS = store_models
    env: Environment = get_env()

    _SOLVER = cast(MathSAT5Solver, env.factory.Solver("msat", solver_options=solver_options))
    converter = _SOLVER.converter

    contextualizer = FormulaContextualizer()
    normalizer = NormalizerWalker(converter)

    atoms = [normalizer.normalize(contextualizer.walk(atom)) for atom in proj_atoms]
    _ATOM_MANAGER = AtomManager(atoms, env)
    _MSAT_ATOMS = [converter.convert(atom) for atom in atoms]

    phi = contextualizer.walk(phi)
    _SOLVER.add_assertion(phi)
    for encoded_tlemma in tlemmas:
        _SOLVER.add_assertion(_ATOM_MANAGER.decode_clause(encoded_tlemma))


def _parallel_worker(model: list[int]) -> tuple[list[EncodedModel], int, list[EncodedClause]]:
    """Worker function for parallel all-smt extension

    Args:
        args: tuple of [TODO]

    Returns:
        tuple of local_models, local_model_count, total_lemmas string
    """
    global _ATOM_MANAGER, _MSAT_ATOMS, _SOLVER, _STORE_MODELS

    solver = cast(MathSAT5Solver, _SOLVER)
    assert solver is not None
    converter = solver.converter
    solver.push()

    atom_manager = cast(AtomManager, _ATOM_MANAGER)
    assert atom_manager is not None

    solver.add_assertions(atom_manager.decode_model(model))

    found_models: list[list[int]] = []
    found_models_count = 0
    if _STORE_MODELS:
        pysmt_models = []
        mathsat.msat_all_sat(
            solver.msat_env(),
            _MSAT_ATOMS,
            callback=lambda model: allsat_callback_store(model, converter, pysmt_models),
        )
        found_models = [atom_manager.encode_model(model) for model in pysmt_models]
        found_models_count = len(found_models)
    else:
        models_count_l = [0]
        mathsat.msat_all_sat(
            solver.msat_env(),
            _MSAT_ATOMS,
            callback=lambda _: allsat_callback_count(models_count_l),
        )
        found_models_count = models_count_l[0]

    pysmt_tlemmas = [converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(solver.msat_env())]

    solver.pop()
    # solver.add_assertions(found_tlemmas)
    found_tlemmas = [atom_manager.encode_clause(lemma) for lemma in pysmt_tlemmas]

    return found_models, found_models_count, found_tlemmas


class DivideStrategy(Protocol):
    @classmethod
    def divide(
        cls, phi: FNode, atoms: list[FNode], n_workers: int, norm: NormalizerWalker
    ) -> tuple[list[list[FNode]], list[FNode]]:
        """
        Partitions the search space of phi into disjoint T-SAT partial assignments.

        Args:
            phi: the formula to divide
            atoms: the atoms to consider for the division (e.g., theory atoms)
            n_workers: the number of workers that will solve the resulting partial assignments in parallel
            norm: normalizer used to normalize returned models and lemmas
        Returns:
            a list of partial assignments covering the search space of phi
            a list of theory lemmas found during the division
        """
        ...


class DivideByPartialAllSMTStrategy(DivideStrategy):
    @classmethod
    def divide(
        cls, phi: FNode, atoms: list[FNode], n_workers: int, norm: NormalizerWalker
    ) -> tuple[list[list[FNode]], list[FNode]]:
        phi = PolarityCNFizer(nnf=True, mutex_nnf_labels=True).convert_as_formula(phi)
        partial_models = []
        with Solver("msat", solver_options=MSAT_PARTIAL_ENUM_OPTIONS) as solver:
            solver.add_assertion(phi)
            converter = solver.converter
            msat_env = solver.msat_env()
            mathsat.msat_all_sat(
                msat_env,
                get_converted_atoms(atoms, converter),
                callback=lambda model: allsat_callback_store(model, converter, partial_models),
            )

            tlemmas = [norm.normalize(converter.back(lemma)) for lemma in mathsat.msat_get_theory_lemmas(msat_env)]
            partial_models = [[norm.normalize(literal) for literal in model] for model in partial_models]

        return partial_models, tlemmas


class DivideByProjectedEnumerationStrategy(DivideStrategy):
    @classmethod
    def divide(
        cls, phi: FNode, atoms, n_workers: int, norm: NormalizerWalker, min_partial_models: int = 0
    ) -> tuple[list[list[FNode]], list[FNode]]:
        if min_partial_models <= 0:
            min_partial_models = n_workers * 100
        atoms = cls._rank_atoms_by_hub_centrality(atoms, phi)
        # choose a number of atoms such that 2**|atoms| >= 10 * n_workers, so to have enough partial models to keep all workers busy
        n_atoms_to_project = min(len(atoms), (min_partial_models - 1).bit_length()) - 1
        partial_models = []
        tlemmas = []
        with Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS) as solver:
            solver.add_assertion(phi)
            converter = solver.converter
            msat_env = solver.msat_env()
            while len(partial_models) < min_partial_models and n_atoms_to_project < len(atoms):
                partial_models.clear()
                n_atoms_to_project += 1
                atoms_to_project = atoms[:n_atoms_to_project]
                solver.push()
                mathsat.msat_all_sat(
                    msat_env,
                    get_converted_atoms(atoms_to_project, converter),
                    callback=lambda model: allsat_callback_store(model, converter, partial_models),
                )
                tlemmas.extend([converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)])
                solver.pop()
        tlemmas = [norm.normalize(lemma) for lemma in tlemmas]
        partial_models = [[norm.normalize(literal) for literal in model] for model in partial_models]

        return partial_models, tlemmas

    @classmethod
    def _rank_atoms_by_hub_centrality(cls, atoms: list[FNode], phi: FNode) -> list[FNode]:
        var_freq = {}
        for atom in atoms:
            for var in atom.get_free_variables():
                var_freq[var] = var_freq.get(var, 0) + 1

        def score(atom):
            return sum(var_freq[v] for v in atom.get_free_variables())

        return sorted(atoms, key=score, reverse=True)


def get_converted_atoms(atoms, converter) -> list[FNode]:
    """Returns a list of normalized atoms"""
    return [converter.convert(a) for a in atoms]


class MathSATExtendedPartialEnumerator(SMTEnumerator):
    """A wrapper for the mathsat T-solver.

    Computes all-SMT by first computing partial assignments and then extending them to total ones.
    The result of the enumeration is a total enumeration of truth assignments."""

    def __init__(
        self,
        computation_logger: dict | None = None,
        project_on_theory_atoms: bool = True,
        parallel_procs: int = 1,
        divide_strategy: type[DivideStrategy] = DivideByPartialAllSMTStrategy,
    ):
        super().__init__(computation_logger=computation_logger)
        if parallel_procs < 1 or parallel_procs > multiprocessing.cpu_count():
            raise ValueError("parallel_procs must be between 1 and the number of CPU cores")
        self.solver_total: MathSAT5Solver = Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS)
        self.reset()
        self._converter_total = self.solver_total.converter
        self._project_on_theory_atoms = project_on_theory_atoms
        self._parallel_procs = parallel_procs
        self._divide_strategy = divide_strategy

    def reset(self):
        self.solver_total.reset_assertions()
        self._tlemmas = []
        self._models = []
        self._models_count = 0

    def check_all_sat(self, phi: FNode, atoms: list[FNode] | None = None, store_models: bool = False) -> bool:
        self.check_supports(phi)
        self.reset()

        atoms = list(phi.get_atoms()) if atoms is None else atoms
        if self._project_on_theory_atoms:
            atoms = get_theory_atoms(atoms)
        if not atoms:
            return self.solver_total.is_sat(phi)

        self.atoms = atoms

        start_time = time.time()
        normalizer = NormalizerWalker(self.get_converter())
        partial_models, tlemmas = self._divide_strategy.divide(phi, atoms, self._parallel_procs, normalizer)
        self._tlemmas = tlemmas
        end_time = time.time()
        if self._computation_logger is not None:
            self._computation_logger["Partial AllSMT time"] = end_time - start_time
            self._computation_logger["Partial models"] = len(partial_models)

        if len(partial_models) == 0:
            return UNSAT

        if self._parallel_procs <= 1:
            self.solver_total.add_assertion(phi)
            self.solver_total.add_assertions(self._tlemmas)
            converted_atoms = get_converted_atoms(atoms, self._converter_total)

            for m in partial_models:
                self.solver_total.push()
                self.solver_total.add_assertions(m)

                if store_models:
                    worker_enc_models = []
                    mathsat.msat_all_sat(
                        self.solver_total.msat_env(),
                        converted_atoms,
                        callback=lambda model: allsat_callback_store(model, self._converter_total, worker_enc_models),
                    )
                    self._models_count += len(worker_enc_models)
                    self._models.extend(worker_enc_models)
                else:
                    models_count_l = [0]
                    mathsat.msat_all_sat(
                        self.solver_total.msat_env(),
                        converted_atoms,
                        callback=lambda _: allsat_callback_count(models_count_l),
                    )
                    self._models_count += models_count_l[0]

                tlemmas_total = [
                    self._converter_total.back(lemma)
                    for lemma in mathsat.msat_get_theory_lemmas(self.solver_total.msat_env())
                ]

                self._tlemmas += tlemmas_total
                self.solver_total.pop()

                self.solver_total.add_assertions(tlemmas_total)

        else:
            # Use a process pool to maintain constant number of workers
            atom_manager = AtomManager(atoms)
            enc_partial_models = [atom_manager.encode_model(model) for model in partial_models]
            enc_tlemmas = [atom_manager.encode_clause(lemma) for lemma in self._tlemmas]
            new_tlemmas = []
            pool = multiprocessing.Pool(
                processes=self._parallel_procs,
                initializer=_initialize_worker,
                initargs=(
                    phi,
                    atoms,
                    enc_tlemmas,
                    MSAT_TOTAL_ENUM_OPTIONS,
                    store_models,
                ),
            )
            with pool:
                # Use imap_unordered to process results as they complete
                total_deserialization_time = 0.0
                for worker_enc_models, work_model_count, worker_enc_tlemmas in pool.imap_unordered(
                    _parallel_worker, enc_partial_models
                ):
                    start_time = time.time()
                    self._models.extend([atom_manager.decode_model(model) for model in worker_enc_models])
                    new_tlemmas.extend([atom_manager.decode_clause(lemma) for lemma in worker_enc_tlemmas])
                    total_deserialization_time += time.time() - start_time
                    self._models_count += work_model_count
                if self._computation_logger is not None:
                    self._computation_logger["Total deserialization time"] = total_deserialization_time

            self._tlemmas.extend(new_tlemmas)

        self._tlemmas = list(set(self._tlemmas))

        if self._computation_logger is not None:
            self._computation_logger["Total models"] = self._models_count

        return SAT

    def get_theory_lemmas(self) -> list[FNode]:
        """Returns the theory lemmas found during the All-SAT computation"""
        return self._tlemmas

    def get_models(self) -> list:
        """Returns the models found during the All-SAT computation"""
        return self._models

    def get_models_count(self) -> int:
        return self._models_count

    def get_converter(self):
        """Returns the converter used for the normalization of T-atoms"""
        return self._converter_total
