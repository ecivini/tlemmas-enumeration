from io import StringIO

from mathsat import msat_term
from pysmt.environment import Environment
from pysmt.formula import FormulaManager

from pysmt.shortcuts import get_env
from pysmt.fnode import FNode
from pysmt.smtlib.parser import SmtLibParser
from pysmt.smtlib.script import smtlibscript_from_formula

from typing import TypeAlias

MSAT_ENUM_OPTIONS = {
    "model_generation": "false",  # force to false so to avoid unnecessary lemmas
    "preprocessor.toplevel_propagation": "false",  # disable non-validity-preserving simplifications
    "preprocessor.simplification": "0",  # same as above
    "dpll.store_tlemmas": "true",  # store T-lemmas
    "theory.la.split_rat_eq": "false",  # avoid generating new atoms for rational equalities
    "theory.bv.eager": "false",  # lazy BV solving (to get lemmas)
    "theory.la.laz_internal_branch_and_bound": "true",  # LIA solving: use internal B&B
    "theory.la.laz_internal_branch_and_bound_limit": "0",
    # "debug.api_call_trace": "3",
}
MSAT_TOTAL_ENUM_OPTIONS = {
    "dpll.allsat_minimize_model": "false",
    **MSAT_ENUM_OPTIONS,
}  # total truth assignments
MSAT_PARTIAL_ENUM_OPTIONS = {
    "dpll.allsat_minimize_model": "true",
    **MSAT_ENUM_OPTIONS,
}  # partial truth assignments


def allsat_callback_count(models: list[int]):
    """callback for total all-sat"""
    # We cannot pass an int as it would be copied by value, so we
    # use a list with just one element, which is the number of models
    models[0] += 1
    return 1


def allsat_callback_store(model, converter, models):
    """callback for partial all-sat"""
    py_model = [converter.back(v) for v in model]
    models.append(py_model)
    return 1


def serialize_formula(formula: FNode) -> str:
    """Serialize a PySMT formula to SMT-LIB text."""
    buff = StringIO()
    smtlibscript_from_formula(formula).serialize(buff)
    return buff.getvalue()


def deserialize_formula(formula_str: str, parser: SmtLibParser) -> FNode:
    """Deserialize SMT-LIB text back into a PySMT formula."""
    script = parser.get_script(StringIO(formula_str))
    return script.get_strict_formula(parser.env.formula_manager)


# A partial model: signed 1-based indices into the known atom list
EncodedModel: TypeAlias = list[int]

# A single clause (T-lemma): known atoms as signed indices + new atoms as SMT-LIB strings
EncodedClause: TypeAlias = tuple[tuple[int, ...], tuple[str, ...]]


class AtomManager:
    """Maps literals to signed indices, with string fallback for unknown atoms.

    The manager is built from the provided atom list and the index of each atom
    in the list is used to compute its  literals' indexes.

    Literals whose atoms are not present in the known atom list are encoded via
    SMT-LIB serialization and decoded by parsing them back when needed.
    """

    def __init__(self, atoms: list[FNode], env: Environment | None = None):
        self.env = get_env() if env is None else env
        self._idx_to_atom = atoms
        self._atom_to_idx: dict[FNode, int] = {a: i for i, a in enumerate(atoms)}
        self._parser = SmtLibParser(self.env)

    @property
    def mgr(self) -> FormulaManager:
        return self.env.formula_manager

    def encode_literal(self, lit: FNode) -> int | str:
        is_neg = lit.is_not()
        atom = lit.arg(0) if is_neg else lit
        idx = self._atom_to_idx.get(atom)
        if idx is not None:
            return -idx - 1 if is_neg else (idx + 1)
        return serialize_formula(lit)

    def encode_model(self, model: list[FNode]) -> EncodedModel:
        """Partial models only contain known atoms; all values must be ints."""
        result = [self.encode_literal(lit) for lit in model]
        assert all(isinstance(v, int) for v in result), (
            "Unexpected unknown atom in partial model: {}, known_atoms: {}".format(model, self._idx_to_atom)
        )
        return result  # type: ignore[return-value]

    def encode_clause(self, clause: FNode) -> EncodedClause:
        """T-lemmas may contain unknown atoms; splits into known indices and new strings."""
        lits = list(clause.args()) if clause.is_or() else [clause]
        known, new = [], []
        while lits:
            lit = lits.pop()
            if lit.is_or():
                lits.extend(lit.args())
            else:
                enc = self.encode_literal(lit)
                (known if isinstance(enc, int) else new).append(enc)
        return tuple(sorted(known, key=lambda v: abs(v))), tuple(sorted(new))

    def decode_literal(self, val: int | str) -> FNode:
        if isinstance(val, int):
            atom = self._idx_to_atom[val - 1] if val > 0 else self._idx_to_atom[-val - 1]
            return atom if val > 0 else self.mgr.Not(atom)
        return deserialize_formula(val, self._parser)

    def decode_model(self, indices: EncodedModel) -> list[FNode]:
        return [self.decode_literal(i) for i in indices]

    def decode_clause(self, clause: EncodedClause) -> FNode:
        known, new = clause
        return self.mgr.Or([self.decode_literal(v) for v in (*known, *new)])


def get_converted_atoms(atoms, converter) -> list[msat_term]:
    """Returns a list of normalized atoms"""
    return [converter.convert(a) for a in atoms]
