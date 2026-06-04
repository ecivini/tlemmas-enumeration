import multiprocessing

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
    EncodedClause,
    allsat_callback_count,
    allsat_callback_store,
    get_converted_atoms,
    remove_subsumed_clauses,
)
from enumerators.solvers.solver import SMTEnumerator
from enumerators.util.pysmt import SuspendTypeChecking
from enumerators.util.timer import Timer
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
        use_divide_tlemmas: Whether to pass the lemmas learned during the divide phase to the
            worker processes.
    """

    def __init__(
        self,
        computation_logger: dict | None = None,
        project_on_theory_atoms: bool = True,
        parallel_procs: int = 1,
        divide_strategy: DivideStrategy | None = None,
        maxtasksperchild: int = 20,
        show_progress: bool = False,
        use_divide_tlemmas: bool = False,
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
        self._use_divide_tlemmas = use_divide_tlemmas

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
        with SuspendTypeChecking():
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
        with self._timer.track_time("Partial AllSMT time"):
            divide_models, divide_tlemmas = self._divide_strategy(
                phi,
                atoms,
                normalizer,
                n_workers=self._parallel_procs,
                show_progress=self._show_progress,
            )

        assert divide_models

        all_atoms = list(
            phi.get_atoms() | set(atoms) | {atom for lemma in divide_tlemmas for atom in lemma.get_atoms()}
        )
        atom_manager = AtomManager(all_atoms)
        seen_tlemmas: set[EncodedClause] = {atom_manager.encode_clause(lemma) for lemma in divide_tlemmas}

        if self._computation_logger is not None:
            self._computation_logger["Partial models"] = len(divide_models)

        with self._timer.track_time("Total AllSMT time"):
            if self._parallel_procs <= 1:
                self.conquer_sequential(
                    phi, atoms, divide_tlemmas, seen_tlemmas, divide_models, atom_manager, store_models
                )
            else:
                self.conquer_parallel(phi, atoms, seen_tlemmas, divide_models, atom_manager, store_models)

        tlemmas_no_redundancy = remove_subsumed_clauses(seen_tlemmas)
        with SuspendTypeChecking():
            self._tlemmas = [atom_manager.decode_clause(c) for c in tlemmas_no_redundancy]

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

    def conquer_sequential(
        self,
        phi: FNode,
        atoms: list[FNode],
        divide_tlemmas: list[FNode],
        seen_tlemmas: set[EncodedClause],
        divide_models: list[list[FNode]],
        atom_manager: AtomManager,
        store_models: bool,
    ) -> None:
        self._solver_total.add_assertion(phi)
        if self._use_divide_tlemmas:
            self._solver_total.add_assertions(divide_tlemmas)
        converted_atoms = get_converted_atoms(atoms, self._converter_total)
        for m in tqdm.tqdm(divide_models, desc="Solving subproblems", disable=not self._show_progress):
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

            with SuspendTypeChecking():
                tlemmas_total = [
                    self._converter_total.back(lemma)
                    for lemma in mathsat.msat_get_theory_lemmas(self._solver_total.msat_env())
                ]
            seen_tlemmas.update(atom_manager.encode_clause(lemma) for lemma in tlemmas_total)
            self._solver_total.pop()

    def conquer_parallel(
        self,
        phi: FNode,
        atoms: list[FNode],
        seen_tlemmas: set[EncodedClause],
        divide_models: list[list[FNode]],
        atom_manager: AtomManager,
        store_models: bool,
    ) -> None:
        proj_atoms = [atom_manager.encode_literal(atom) for atom in atoms]
        enc_partial_models = [atom_manager.encode_model(model) for model in divide_models]
        worker_tlemmas = list(seen_tlemmas) if self._use_divide_tlemmas else []
        with multiprocessing.Pool(
            processes=self._parallel_procs,
            initializer=initialize_worker,
            initargs=(phi, atom_manager.atoms, proj_atoms, worker_tlemmas, MSAT_TOTAL_ENUM_OPTIONS, store_models),
            maxtasksperchild=self._maxtasksperchild,
        ) as pool:
            for worker_enc_models, work_model_count, worker_enc_tlemmas in tqdm.tqdm(
                pool.imap_unordered(parallel_worker, enc_partial_models),
                desc="Solving subproblems",
                total=len(enc_partial_models),
                disable=not self._show_progress,
            ):
                with SuspendTypeChecking(), self._timer.track_time("Total deserialization time"):
                    self._models.extend([atom_manager.decode_model(model) for model in worker_enc_models])
                    seen_tlemmas.update(worker_enc_tlemmas)
                self._models_count += work_model_count
