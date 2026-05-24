"""interface that all solvers must implement."""

from abc import ABC, abstractmethod

from pysmt.fnode import FNode

from enumerators.walkers.term_ite_checker import TermIteChecker


class SMTEnumerator(ABC):
    """interface that all solvers must implement.

    This interface must be implemented by all the solvers that are used to compute all-SMT.
    """

    def __init__(self, computation_logger: dict | None = None):
        self._tlemmas = []
        self._computation_logger = computation_logger

    @property
    def computation_logger(self) -> dict | None:
        return self._computation_logger

    @computation_logger.setter
    def computation_logger(self, value: dict | None) -> None:
        self._computation_logger = value

    @abstractmethod
    def reset(self) -> None:
        """Resets the internal state of the solver"""
        pass

    @abstractmethod
    def check_all_sat(self, phi: FNode, atoms: list[FNode] | None = None, store_models: bool = False) -> bool:
        """Runs All-SMT on the formula phi and stores t-lemmas

        Args:
            phi (FNode): a pysmt formula
            atoms (list[FNode] | None) [None]: list of atoms to consider for All-SMT
            store_models (bool) [False]: if True, the models found during All-SMT are stored

        Returns:
            bool: SAT or UNSAT, depending on satisfiability of phi
        """
        pass

    @abstractmethod
    def get_theory_lemmas(self) -> list[FNode]:
        """return the list of theory lemmas"""
        pass

    @abstractmethod
    def get_converter(self) -> object:
        """return the converter for normalization of T-atoms"""
        pass

    @abstractmethod
    def get_models(self) -> list[list[FNode]]:
        """return the list of models"""
        pass

    @abstractmethod
    def get_models_count(self) -> int:
        """return the number of models"""
        pass

    @staticmethod
    def check_supports(phi: FNode) -> None:
        """check if the solver supports the formula phi

        Args:
            phi (FNode): a pysmt formula
        Returns:
            bool: True if the solver supports phi, False otherwise
        """
        assert TermIteChecker().walk(phi), "Term-ITE are not supported yet"
