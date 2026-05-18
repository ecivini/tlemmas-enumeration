"""this module handles interactions with the mathsat solver"""

import multiprocessing
import time
from typing import Protocol, cast

import mathsat
from allsat_cnf.polarity_cnfizer import PolarityCNFizer
from pysmt.fnode import FNode
from pysmt.formula import FormulaContextualizer
from pysmt.shortcuts import And, Solver
from pysmt.smtlib.parser import SmtLibParser
from pysmt.solvers.msat import MathSAT5Solver

from enumerators.constants import SAT, UNSAT
from enumerators.formula import get_theory_atoms
from enumerators.solvers.solver import SMTEnumerator
from .mathsat_utils import (
    MSAT_PARTIAL_ENUM_OPTIONS,
    MSAT_TOTAL_ENUM_OPTIONS,
    allsat_callback_count,
    allsat_callback_store,
    deserialize_conjunction,
    serialize_conjunction,
)


_PARTIAL_MODELS = []
_TLEMMAS = []
_PHI = None
_PHI_ATOMS = []
_SOLVER: MathSAT5Solver | None = None
_CONTEXTUALIZER: FormulaContextualizer | None = None


def _initialize_worker(
    partial_models: list[list[FNode]],
    phi: FNode,
    phi_atoms: list[FNode],
    tlemmas: list[FNode],
    solver_options: dict,
) -> None:
    global _PARTIAL_MODELS, _TLEMMAS, _PHI, _PHI_ATOMS, _SOLVER, _CONTEXTUALIZER

    contextualizer = FormulaContextualizer()
    _CONTEXTUALIZER = contextualizer

    _PARTIAL_MODELS = partial_models
    _TLEMMAS = [contextualizer.walk(lemma) for lemma in tlemmas]
    _PHI = contextualizer.walk(phi)

    _SOLVER = cast(MathSAT5Solver, Solver("msat", solver_options=solver_options))
    converter = _SOLVER.converter

    _PHI_ATOMS = [converter.convert(contextualizer.walk(atom)) for atom in phi_atoms]

    _SOLVER.add_assertion(_PHI)
    _SOLVER.add_assertions(_TLEMMAS)


def _parallel_worker(args: tuple) -> tuple[list[str], int, str]:
    """Worker function for parallel all-smt extension

    Args:
        args: tuple of (partial_model, phi, atoms, solver_options_dict_total, tlemmas)

    Returns:
        tuple of local_models, local_model_count, total_lemmas string
    """
    global _PARTIAL_MODELS, _TLEMMAS, _PHI, _PHI_ATOMS, _SOLVER, _CONTEXTUALIZER

    model_id, store_models = args

    solver = cast(MathSAT5Solver, _SOLVER)
    assert solver is not None
    converter = solver.converter

    contextualizer = cast(FormulaContextualizer, _CONTEXTUALIZER)
    converted_atoms = _PHI_ATOMS

    model = _PARTIAL_MODELS[model_id]

    solver.push()

    model = [contextualizer.walk(lit) for lit in model]
    solver.add_assertions(model)

    found_models = []
    found_models_count = 0
    if store_models:
        mathsat.msat_all_sat(
            solver.msat_env(),
            converted_atoms,
            callback=lambda model: allsat_callback_store(model, converter, found_models),
        )
        found_models_count = len(found_models)
        found_models = [serialize_conjunction(model) for model in found_models]
    else:
        models_count_l = [0]
        mathsat.msat_all_sat(
            solver.msat_env(),
            converted_atoms,
            callback=lambda _: allsat_callback_count(models_count_l),
        )
        found_models_count = models_count_l[0]

    found_tlemmas = [converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(solver.msat_env())]

    solver.pop()
    solver.add_assertions(found_tlemmas)

    return found_models, found_models_count, serialize_conjunction(found_tlemmas)


class DivideStrategy(Protocol):
    @classmethod
    def divide(cls, phi: FNode, atoms: list[FNode], n_workers: int) -> tuple[list[list[FNode]], list[FNode]]:
        """
        Partitions the search space of phi into disjoint T-SAT partial assignments.

        Args:
            phi: the formula to divide
            atoms: the atoms to consider for the division (e.g., theory atoms)
            n_workers: the number of workers that will solve the resulting partial assignments in parallel
        Returns:
            a list of partial assignments covering the search space of phi
            a list of theory lemmas found during the division
        """
        ...


class DivideByPartialAllSMTStrategy(DivideStrategy):
    @classmethod
    def divide(cls, phi: FNode, atoms: list[FNode], n_workers: int) -> tuple[list[list[FNode]], list[FNode]]:
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

            tlemmas = [converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)]
        return partial_models, tlemmas


class DivideByProjectedEnumerationStrategy(DivideStrategy):
    @classmethod
    def divide(
        cls, phi: FNode, atoms, n_workers: int, min_partial_models: int = 0
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
        self.solver_total = Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS)
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
        self.atoms = atoms

        start_time = time.time()
        partial_models, tlemmas = self._divide_strategy.divide(phi, atoms, self._parallel_procs)
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
                    models = []
                    mathsat.msat_all_sat(
                        self.solver_total.msat_env(),
                        converted_atoms,
                        callback=lambda model: allsat_callback_store(model, self._converter_total, models),
                    )
                    self._models_count += len(models)
                    self._models.extend(models)
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

                self.solver_total.add_assertion(And(tlemmas_total))

        else:
            # Prepare arguments for each worker
            worker_args = [(i, store_models) for i in range(len(partial_models))]

            # Use a process pool to maintain constant number of workers
            new_tlemmas = []
            pool = multiprocessing.Pool(
                processes=self._parallel_procs,
                initializer=_initialize_worker,
                initargs=(
                    partial_models,
                    phi,
                    atoms,
                    self._tlemmas,
                    MSAT_TOTAL_ENUM_OPTIONS,
                ),
            )
            parser = SmtLibParser()
            with pool:
                # Use imap_unordered to process results as they complete
                total_deserialization_time = 0.0
                for models, models_count, lemmas_batch_str in pool.imap_unordered(_parallel_worker, worker_args):
                    self._models.extend([deserialize_conjunction(model_str, parser) for model_str in models])
                    start_time = time.time()
                    new_tlemmas.extend(deserialize_conjunction(lemmas_batch_str, parser))
                    total_deserialization_time += time.time() - start_time
                    self._models_count += models_count
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
