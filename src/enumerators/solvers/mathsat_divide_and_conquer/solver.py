import multiprocessing

import mathsat
import tqdm
from pysmt.fnode import FNode
from pysmt.shortcuts import Solver
from pysmt.solvers.msat import MSatConverter, MathSAT5Solver

from enumerators.solvers.mathsat_divide_and_conquer.conquer import initialize_worker, parallel_worker
from enumerators.solvers.mathsat_divide_and_conquer.divide import (
    DivideByPartialAllSMTStrategy,
    DivideStrategy,
)
from enumerators.solvers.mathsat_utils import (
    MSAT_TOTAL_ENUM_OPTIONS,
    AtomManager,
    EncodedClause,
    EncodedModel,
    allsat_callback_count,
    allsat_callback_store,
    get_converted_atoms,
)
from enumerators.solvers.solver import SMTEnumerator
from enumerators.util.pysmt import SuspendTypeChecking


class MathSATDivideAndConquerEnumerator(SMTEnumerator):
    """All-SMT enumerator using divide-and-conquer over partial assignments.

    Computes All-SMT by first dividing the search space via partial assignments
    (cubes), then extending each partial assignment to a total one
    (sequentially or in parallel).

    Args:
        computation_logger: Optional dict for profiling timings and counters.
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
        computation_logger: dict[str, object] | None = None,
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
            atoms: Atoms to project on.  If ``None``, all atoms of ``phi`` are used.
            store_models: If ``True``, store enumerated models in-memory
                (accessible via :meth:`get_models`).  If ``False``, only count
                them (:meth:`get_models_count`).

        Returns:
            ``True`` if ``phi`` is satisfiable (models were enumerated),
            ``False`` if unsatisfiable.
        """
        self.check_supports(phi)
        self.reset()
        atoms = list(phi.get_atoms()) if atoms is None else atoms
        self.atoms = atoms

        converter = self._converter_total

        if not (is_sat := self._solver_total.is_sat(phi)) or not atoms:
            msat_env = self._solver_total.msat_env()
            self._tlemmas = [converter.back(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)]
            return is_sat

        known_atoms = list(phi.get_atoms() | set(atoms))
        atom_manager = AtomManager(known_atoms, converter=converter)

        seen_tlemmas: set[EncodedClause] = set()

        with self._stats.track_time("Divide time"):
            divide_enc_models, divide_enc_tlemmas = self._divide_strategy(
                phi,
                atoms,
                atom_manager,
                n_workers=self._parallel_procs,
                show_progress=self._show_progress,
            )

        assert divide_enc_models

        seen_tlemmas.update(divide_enc_tlemmas)

        self._stats.log("Divide models", len(divide_enc_models))
        self._stats.log("Divide lemmas", len(divide_enc_tlemmas))

        with self._stats.track_time("Conquer time"):
            if self._parallel_procs <= 1:
                self.conquer_sequential(phi, atoms, seen_tlemmas, divide_enc_models, atom_manager, store_models)
            else:
                self.conquer_parallel(phi, atoms, seen_tlemmas, divide_enc_models, atom_manager, store_models)

        with SuspendTypeChecking(), self._stats.track_time("Lemmas conversion time"):
            self._tlemmas = [atom_manager.decode_clause_pysmt(lemma) for lemma in seen_tlemmas]

        self._stats.log("Total models", self._models_count)
        self._stats.log("Lemmas", len(self._tlemmas))

        return True

    def get_theory_lemmas(self) -> list[FNode]:
        """Returns the theory lemmas found during the All-SAT computation"""
        return self._tlemmas

    def get_models(self) -> list:
        """Returns the models found during the All-SAT computation"""
        return self._models

    def get_models_count(self) -> int:
        return self._models_count

    def get_converter(self) -> MSatConverter:
        """Returns the converter used for the normalization of T-atoms"""
        return self._converter_total

    def conquer_sequential(
        self,
        phi: FNode,
        atoms: list[FNode],
        seen_tlemmas: set[EncodedClause],
        divide_models: list[EncodedModel],
        atom_manager: AtomManager,
        store_models: bool,
    ) -> None:
        self._solver_total.add_assertion(phi)
        msat_env = self._solver_total.msat_env()
        converter = self._solver_total.converter
        if self._use_divide_tlemmas:
            for lemma in seen_tlemmas:
                mathsat.msat_assert_formula(msat_env, atom_manager.decode_clause_msat(lemma))
        converted_atoms = get_converted_atoms(atoms, converter)
        for enc_model in tqdm.tqdm(divide_models, desc="Solving subproblems", disable=not self._show_progress):
            self._solver_total.push()
            for lit in atom_manager.decode_model_msat(enc_model):
                mathsat.msat_assert_formula(msat_env, lit)

            if store_models:
                msat_models_total = []
                mathsat.msat_all_sat(
                    msat_env,
                    converted_atoms,
                    callback=lambda model: allsat_callback_store(model, msat_models_total),
                )
                self._models_count += len(msat_models_total)
                with SuspendTypeChecking():
                    self._models += [[converter.back(lit) for lit in model] for model in msat_models_total]
            else:
                models_count_l = [0]
                mathsat.msat_all_sat(
                    msat_env,
                    converted_atoms,
                    callback=lambda _: allsat_callback_count(models_count_l),
                )
                self._models_count += models_count_l[0]

            tlemmas_total = [
                atom_manager.encode_clause_msat(lemma) for lemma in mathsat.msat_get_theory_lemmas(msat_env)
            ]
            seen_tlemmas.update(tlemmas_total)
            self._solver_total.pop()

    def conquer_parallel(
        self,
        phi: FNode,
        atoms: list[FNode],
        seen_tlemmas: set[EncodedClause],
        divide_enc_models: list[EncodedModel],
        atom_manager: AtomManager,
        store_models: bool,
    ) -> None:
        proj_atoms = [atom_manager.encode_literal_pysmt(atom) for atom in atoms]
        worker_tlemmas = list(seen_tlemmas) if self._use_divide_tlemmas else []
        with multiprocessing.Pool(
            processes=self._parallel_procs,
            initializer=initialize_worker,
            initargs=(phi, atom_manager.atoms, proj_atoms, worker_tlemmas, MSAT_TOTAL_ENUM_OPTIONS, store_models),
            maxtasksperchild=self._maxtasksperchild,
        ) as pool:
            for worker_enc_models, work_model_count, worker_enc_tlemmas in tqdm.tqdm(
                pool.imap_unordered(parallel_worker, divide_enc_models),
                desc="Solving subproblems",
                total=len(divide_enc_models),
                disable=not self._show_progress,
            ):
                with SuspendTypeChecking(), self._stats.track_time("Total deserialization time"):
                    if store_models:
                        self._models.extend([atom_manager.decode_model_pysmt(model) for model in worker_enc_models])
                    seen_tlemmas.update(worker_enc_tlemmas)
                self._models_count += work_model_count
