import multiprocessing
import time

import mathsat
import tqdm
from pysmt.fnode import FNode
from pysmt.shortcuts import Solver
from pysmt.solvers.msat import MathSAT5Solver

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
    """All-SMT enumerator using divide-and-conquer over partial assignments.

    Computes All-SMT by first dividing the search space via partial assignments
    (cubes), then extending each partial assignment to a total one
    (sequentially or in parallel).

    Args:
        computation_logger: Optional dict for profiling timings and counters.
        project_on_theory_atoms: If ``True``, enumeration is projected on theory atoms only
        parallel_procs: Number of parallel worker processes for the total enumeration phase.
        divide_strategy: A :class:`DivideStrategy` instance.  If ``None``,
            defaults to :class:`DivideByPartialAllSMTStrategy`.
        maxtasksperchild: Maximum number of tasks a worker process can complete before being
            replaced.
        show_progress: Whether to display ``tqdm`` progress bars during
            the divide and total enumeration phases.
    """

    def __init__(
        self,
        computation_logger: dict | None = None,
        project_on_theory_atoms: bool = True,
        parallel_procs: int = 1,
        divide_strategy: DivideStrategy | None = None,
        maxtasksperchild: int = 20,
        show_progress: bool = False,
    ):
        super().__init__(computation_logger=computation_logger)
        if parallel_procs < 1 or parallel_procs > multiprocessing.cpu_count():
            raise ValueError("parallel_procs must be between 1 and the number of CPU cores")
        self._solver_total: MathSAT5Solver = Solver("msat", solver_options=MSAT_TOTAL_ENUM_OPTIONS)
        self.reset()
        self._converter_total = self._solver_total.converter
        self._project_on_theory_atoms = project_on_theory_atoms
        self._parallel_procs = parallel_procs
        self._divide_strategy = divide_strategy if divide_strategy is not None else DivideByPartialAllSMTStrategy()
        self._maxtasksperchild = maxtasksperchild
        self._show_progress = show_progress

    def reset(self):
        self._solver_total.reset_assertions()
        self._tlemmas = []
        self._models = []
        self._models_count = 0

    def check_all_sat(self, phi: FNode, atoms: list[FNode] | None = None, store_models: bool = False) -> bool:
        """Enumerate all satisfying assignments of ``phi``.

        Args:
            phi: Formula to enumerate truth assignments for.
            atoms: Atoms to project on.  If ``None``, all atoms of ``phi`` are
                used (filtered by ``project_on_theory_atoms`` if enabled).
            store_models: If ``True``, store enumerated models in-memory
                (accessible via :meth:`get_models`).  If ``False``, only count
                them (:meth:`get_models_count`).

        Returns:
            ``True`` if ``phi`` is satisfiable (models were enumerated),
            ``False`` if unsatisfiable.
        """
        self.check_supports(phi)
        self.reset()

        converter = self._converter_total
        msat_env = self._solver_total.msat_env()

        is_sat = self._solver_total.is_sat(phi)
        self._tlemmas = [converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)]
        if not is_sat:
            return False

        atoms = list(phi.get_atoms()) if atoms is None else atoms
        if self._project_on_theory_atoms:
            atoms = get_theory_atoms(atoms)
        if not atoms:
            return True

        self.atoms = atoms

        normalizer = NormalizerWalker(converter)
        start_time = time.time()
        partial_models, tlemmas = self._divide_strategy(
            phi, atoms, normalizer, n_workers=self._parallel_procs, show_progress=self._show_progress
        )
        self._tlemmas.extend(tlemmas)

        end_time = time.time()
        if self._computation_logger is not None:
            self._computation_logger["Partial AllSMT time"] = end_time - start_time
            self._computation_logger["Partial models"] = len(partial_models)

        assert partial_models

        if self._parallel_procs <= 1:
            self._solver_total.add_assertion(phi)
            self._solver_total.add_assertions(self._tlemmas)
            converted_atoms = get_converted_atoms(atoms, self._converter_total)

            for m in tqdm.tqdm(partial_models, desc="Solving subproblems", disable=not self._show_progress):
                self._solver_total.push()
                self._solver_total.add_assertions(m)

                if store_models:
                    worker_enc_models = []
                    mathsat.msat_all_sat(
                        self._solver_total.msat_env(),
                        converted_atoms,
                        callback=lambda model: allsat_callback_store(model, self._converter_total, worker_enc_models),
                    )
                    self._models_count += len(worker_enc_models)
                    self._models.extend(worker_enc_models)
                else:
                    models_count_l = [0]
                    mathsat.msat_all_sat(
                        self._solver_total.msat_env(),
                        converted_atoms,
                        callback=lambda _: allsat_callback_count(models_count_l),
                    )
                    self._models_count += models_count_l[0]

                tlemmas_total = [
                    self._converter_total.back(lemma)
                    for lemma in mathsat.msat_get_theory_lemmas(self._solver_total.msat_env())
                ]

                self._tlemmas += tlemmas_total
                self._solver_total.pop()

                self._solver_total.add_assertions(tlemmas_total)

        else:
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

        return True

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
