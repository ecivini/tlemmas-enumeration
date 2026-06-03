import multiprocessing
import time

import mathsat
import tqdm
from pysmt.fnode import FNode
from pysmt.shortcuts import Solver
from pysmt.solvers.msat import MathSAT5Solver

from enumerators.constants import SAT, UNSAT
from enumerators.formula import get_theory_atoms
from enumerators.solvers.mathsat_divide_and_conquer.conquer import initialize_worker, parallel_worker
from enumerators.solvers.mathsat_divide_and_conquer.divide import (
    DivideByPartialAllSMTStrategy,
    DivideStrategy,
)
from enumerators.solvers.mathsat_utils import (
    MSAT_TOTAL_ENUM_OPTIONS,
    AtomManager,
    allsat_callback_count,
    allsat_callback_store,
    get_converted_atoms,
)
from enumerators.solvers.solver import SMTEnumerator
from enumerators.walkers.normalizer import NormalizerWalker


class MathSATDivideAndConquerEnumerator(SMTEnumerator):
    """A wrapper for the mathsat T-solver.

    Computes all-SMT by first computing partial assignments and then extending them to total ones.
    The result of the enumeration is a total enumeration of truth assignments."""

    def __init__(
        self,
        computation_logger: dict | None = None,
        project_on_theory_atoms: bool = True,
        parallel_procs: int = 1,
        divide_strategy: type[DivideStrategy] = DivideByPartialAllSMTStrategy,
        maxtasksperchild: int = 20,
        show_progress: bool = False,
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
        self._maxtasksperchild = maxtasksperchild
        self._show_progress = show_progress

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

            for m in tqdm.tqdm(partial_models, desc="Solving subproblems", disable=not self._show_progress):
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
            all_atoms = list(
                phi.get_atoms() | set(atoms) | {atom for lemma in self._tlemmas for atom in lemma.get_atoms()}
            )
            atom_manager = AtomManager(all_atoms)
            proj_atoms = [atom_manager.encode_literal(atom) for atom in atoms]
            enc_partial_models = [atom_manager.encode_model(model) for model in partial_models]
            enc_tlemmas = [atom_manager.encode_clause(lemma) for lemma in self._tlemmas]
            new_tlemmas: list[FNode] = []
            seen_tlemmas = set(enc_tlemmas)
            with multiprocessing.Pool(
                processes=self._parallel_procs,
                initializer=initialize_worker,
                initargs=(phi, all_atoms, proj_atoms, enc_tlemmas, MSAT_TOTAL_ENUM_OPTIONS, store_models),
                maxtasksperchild=self._maxtasksperchild,
            ) as pool:
                # Use imap_unordered to process results as they complete
                total_deserialization_time = 0.0
                for worker_enc_models, work_model_count, worker_enc_tlemmas in tqdm.tqdm(
                    pool.imap_unordered(parallel_worker, enc_partial_models),
                    desc="Solving subproblems",
                    total=len(enc_partial_models),
                    disable=not self._show_progress,
                ):
                    start_time = time.time()
                    self._models.extend([atom_manager.decode_model(model) for model in worker_enc_models])
                    unique_tlemmas = set(worker_enc_tlemmas) - seen_tlemmas
                    if unique_tlemmas:
                        seen_tlemmas.update(unique_tlemmas)
                        new_tlemmas.extend(atom_manager.decode_clause(lemma) for lemma in unique_tlemmas)
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
