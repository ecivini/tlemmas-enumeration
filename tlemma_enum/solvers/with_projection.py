from pysmt.fnode import FNode
from pysmt.solvers.msat import MSatConverter

from tlemma_enum.formula import get_theory_atoms
from tlemma_enum.solvers.solver import SMTEnumerator


class WithProjectionWrapper(SMTEnumerator):
    """Wrapper that projects All-SMT onto theory atoms only.

    Filters the atom list passed to ``check_all_sat`` through
    ``get_theory_atoms()``, removing any propositional (non-theory)
    atoms before delegating to the base solver.

    Composition:
        Wrap any ``SMTEnumerator`` to restrict enumeration to theory atoms.
        Stacking order matters: should be the outermost wrapper unless
        you specifically need a different order.

    Note:
        ``WithPartitioningWrapper`` already projects onto theory atoms
        internally, so wrapping a partitioned solver in
        ``WithProjectionWrapper`` is redundant (but harmless).
    """

    def __init__(
        self,
        base_solver: SMTEnumerator,
        computation_logger: dict[str, object] | None = None,
    ) -> None:
        self._base_solver = base_solver
        super().__init__(computation_logger)

    def reset(self) -> None:
        self._base_solver.reset()

    def check_all_sat(
        self,
        phi: FNode,
        atoms: list[FNode] | None = None,
        store_models: bool = False,
    ) -> bool:
        atoms = list(phi.get_atoms()) if atoms is None else atoms
        atoms = get_theory_atoms(atoms)
        return self._base_solver.check_all_sat(phi, atoms, store_models)

    def get_theory_lemmas(self) -> list[FNode]:
        return self._base_solver.get_theory_lemmas()

    def get_converter(self) -> MSatConverter:
        return self._base_solver.get_converter()

    def get_models(self) -> list:
        return self._base_solver.get_models()

    def get_models_count(self) -> int:
        return self._base_solver.get_models_count()

    @property
    def computation_logger(self) -> dict[str, object] | None:
        return self._base_solver.computation_logger

    @computation_logger.setter
    def computation_logger(self, value: dict[str, object] | None) -> None:
        self._base_solver.computation_logger = value
