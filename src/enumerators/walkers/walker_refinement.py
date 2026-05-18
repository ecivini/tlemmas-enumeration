from pysmt.environment import Environment
from pysmt.formula import FormulaManager
from pysmt.walkers import DagWalker, handles
import pysmt.operators as op
from pysmt.fnode import FNode


class RefinementWalker(DagWalker):
    """A walker that converts an abstracted formula into its refinment"""

    def __init__(
        self,
        abstraction: dict[FNode, FNode],
        env: Environment | None = None,
        invalidate_memoization: bool = False,
    ):
        DagWalker.__init__(self, env, invalidate_memoization)
        self.refinement = {v: k for k, v in abstraction.items()}
        return

    @property
    def mgr(self) -> FormulaManager:
        return self.env.formula_manager

    def _refine(self, formula):
        assert formula in self.refinement, f"Formula {formula} not in abstraction mapping"
        return self.refinement[formula]

    @handles(*op.RELATIONS, op.FUNCTION)
    def walk_theory(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        return self._refine(formula)

    @handles(op.SYMBOL, *op.CONSTANTS, *op.THEORY_OPERATORS)
    def walk_noop(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        if formula in self.refinement:
            return self._refine(formula)
        # symbols and constants do not change
        return formula

    @handles(*op.BOOL_CONNECTIVES, op.ITE)
    def walk_bool_op(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        # Boolean connectives just connect normalized children
        return self.mgr.create_node(formula.node_type(), tuple(args))
