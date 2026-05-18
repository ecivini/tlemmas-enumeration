import pysmt.operators as op
from pysmt.environment import Environment
from pysmt.fnode import FNode
from pysmt.formula import FormulaManager
from pysmt.typing import BOOL
from pysmt.walkers import DagWalker, handles


class BooleanAbstractionWalker(DagWalker):
    """A walker to normalize smt formulas into its boolean abstraction"""

    def __init__(
        self,
        atoms: list[FNode] | None = None,
        abstraction: dict[FNode, FNode] | None = None,
        env: Environment | None = None,
        invalidate_memoization: bool = False,
    ):
        DagWalker.__init__(self, env, invalidate_memoization)
        self.atoms = atoms if atoms is not None else []
        self.abstraction = abstraction if abstraction is not None else {}

        for atom in self.atoms:
            self._abstract(atom)

    @property
    def mgr(self) -> FormulaManager:
        return self.env.formula_manager

    def _abstract(self, formula: FNode) -> FNode:
        if formula not in self.abstraction:
            var_name = f"v{len(self.abstraction)}"
            abstr_var = self.mgr.Symbol(var_name, BOOL)
            self.abstraction[formula] = abstr_var
        return self.abstraction[formula]

    @handles(*op.RELATIONS, op.FUNCTION)
    def walk_theory(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        return self._abstract(formula)

    @handles(op.SYMBOL, *op.CONSTANTS, *op.THEORY_OPERATORS)
    def walk_noop(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        # symbols and constants do not change
        return formula

    @handles(op.BOOL_CONNECTIVES)
    def walk_bool_op(self, formula: FNode, args: tuple[FNode], **kwargs) -> FNode:
        # Boolean connectives just connect normalized children
        return self.mgr.create_node(formula.node_type(), tuple(args))
