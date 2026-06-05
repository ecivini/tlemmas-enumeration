"""this module defines a Walker that takes a pysmt formula and normalizes its atoms"""

from pysmt.environment import Environment
import pysmt.operators as op
from pysmt.fnode import FNode
from pysmt.formula import FormulaManager
from pysmt.solvers.msat import MSatConverter
from pysmt.walkers import DagWalker, handles


class NormalizerWalker(DagWalker):
    """A walker to normalize smt formulas according to a converter"""

    def __init__(self, converter: MSatConverter, env: Environment | None = None, invalidate_memoization: bool = False):
        DagWalker.__init__(self, env, invalidate_memoization)
        assert converter.env == self.env
        self._converter = converter
        return

    @property
    def mgr(self) -> FormulaManager:
        return self.env.formula_manager

    @handles(*op.RELATIONS, op.FUNCTION)
    def walk_theory(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        # Theory atoms get normalized
        msat_term = self._converter.convert(formula)
        return self._converter.back(msat_term)

    @handles(op.SYMBOL, *op.CONSTANTS, *op.THEORY_OPERATORS)
    def walk_noop(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        # symbols and constants do not change
        return formula

    @handles(*op.BOOL_CONNECTIVES, op.ITE)
    def walk_bool_op(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        if formula.is_not():
            return self.mgr.Not(args[0])
        # Boolean connectives just connect normalized children
        return self.mgr.create_node(formula.node_type(), tuple(args))

    def normalize(self, formula: FNode) -> FNode:
        return self.walk(formula)
