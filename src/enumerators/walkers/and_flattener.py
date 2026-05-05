from pysmt import operators as op
from pysmt.fnode import FNode
from pysmt.walkers import DagWalker, handles


class AndFlattener(DagWalker):
    """Flattens top-level "And" operators into a set of sub-formulas.

    Nested And operators inside other boolean connectives are preserved intact and not flattened.
    E.g.: (a AND (b AND (c OR d))) will be flattened to {a, b, (c OR d)}
    """

    @handles(
        op.CONSTANTS
        | op.THEORY_OPERATORS
        | op.RELATIONS
        | {op.SYMBOL, op.FUNCTION, op.ITE}
        | (op.BOOL_CONNECTIVES - {op.AND})
    )
    def walk_any(self, formula, args, **kwargs):
        return frozenset([formula])

    def walk_and(self, formula, args, **kwargs) -> frozenset[FNode]:
        return frozenset().union(*args)

    def flatten(self, formula: FNode) -> frozenset[FNode]:
        return self.walk(formula)
