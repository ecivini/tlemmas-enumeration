from io import StringIO
from typing import TypeAlias

import mathsat
from pysmt.environment import Environment
from pysmt.fnode import FNode
from pysmt.formula import FormulaManager
from pysmt.shortcuts import get_env
from pysmt.smtlib.parser import SmtLibParser
from pysmt.smtlib.script import smtlibscript_from_formula
from pysmt.solvers.msat import MSatConverter

from tlemma_enum.util.pysmt import SuspendTypeChecking

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


def allsat_callback_store(model, models):
    """callback for partial all-sat"""
    models.append(list(model))
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

    def __init__(self, atoms: list[FNode], converter: MSatConverter, env: Environment | None = None):
        self.env = get_env() if env is None else env
        self._converter = converter

        msat_atoms = [
            mathsat.msat_term_get_arg(catom, 0)
            if mathsat.msat_term_is_not(self.msat_env, (catom := converter.convert(atom)))
            else catom
            for atom in atoms
        ]
        with SuspendTypeChecking():
            pysmt_atoms = [converter.back(msat_atom) for msat_atom in msat_atoms]

        self._idx_to_pysmt_atom = pysmt_atoms
        self._idx_to_msat_atom = msat_atoms

        self._pysmt_atom_to_idx: dict[FNode, int] = {a: i for i, a in enumerate(pysmt_atoms)}
        self._msat_atom_to_idx: dict[mathsat.msat_term, int] = {a: i for i, a in enumerate(msat_atoms)}

        self._parser = SmtLibParser(self.env)

    @property
    def atoms(self) -> list[FNode]:
        return list(self._idx_to_pysmt_atom)

    @property
    def mgr(self) -> FormulaManager:
        return self.env.formula_manager

    @property
    def msat_env(self) -> mathsat.msat_env:
        return self._converter.msat_env()

    def encode_literal_pysmt(self, lit: FNode) -> int | str:
        is_neg = lit.is_not()
        atom = lit.arg(0) if is_neg else lit
        idx = self._pysmt_atom_to_idx.get(atom)
        if idx is not None:
            return -idx - 1 if is_neg else (idx + 1)
        return serialize_formula(lit)

    def encode_literal_msat(self, lit: mathsat.msat_term) -> int | str:
        is_neg = mathsat.msat_term_is_not(self.msat_env, lit)
        atom = mathsat.msat_term_get_arg(lit, 0) if is_neg else lit
        idx = self._msat_atom_to_idx.get(atom)
        if idx is not None:
            return -idx - 1 if is_neg else (idx + 1)
        pysmt_lit = self._converter.back(lit)
        return serialize_formula(pysmt_lit)

    def encode_model_pysmt(self, model: list[FNode]) -> EncodedModel:
        """Partial models only contain known atoms; all values must be ints."""
        result = [self.encode_literal_pysmt(lit) for lit in model]
        assert all(isinstance(v, int) for v in result), "Unexpected unknown atom in model: {}, known_atoms: {}".format(
            model, self._idx_to_pysmt_atom
        )
        return result  # type: ignore[return-value]

    def encode_model_msat(self, model: list[mathsat.msat_term]) -> EncodedModel:
        result = [self.encode_literal_msat(lit) for lit in model]
        assert all(isinstance(v, int) for v in result), "Unexpected unknown atom in model: {}, known_atoms: {}".format(
            model, self._idx_to_pysmt_atom
        )
        return result  # type: ignore[return-value]

    def encode_clause_pysmt(self, clause: FNode) -> EncodedClause:
        """T-lemmas may contain unknown atoms; splits into known indices and new strings."""
        lits = [clause]
        known, new = [], []
        while lits:
            lit = lits.pop()
            if lit.is_or():
                lits.extend(lit.args())
            else:
                enc = self.encode_literal_pysmt(lit)
                (known if isinstance(enc, int) else new).append(enc)
        return tuple(sorted(known, key=lambda v: abs(v))), tuple(sorted(new))

    def encode_clause_msat(self, clause: mathsat.msat_term) -> EncodedClause:
        lits = [clause]
        known, new = [], []
        while lits:
            lit = lits.pop()
            if mathsat.msat_term_is_or(self.msat_env, lit):
                arity = mathsat.msat_term_arity(lit)
                lits.extend([mathsat.msat_term_get_arg(lit, i) for i in range(arity)])
            else:
                enc = self.encode_literal_msat(lit)
                (known if isinstance(enc, int) else new).append(enc)
        return tuple(sorted(known, key=lambda v: abs(v))), tuple(sorted(new))

    def decode_literal_pysmt(self, val: int | str) -> FNode:
        if isinstance(val, int):
            atom = self._idx_to_pysmt_atom[abs(val) - 1]
            return atom if val > 0 else self.mgr.Not(atom)
        return deserialize_formula(val, self._parser)

    def decode_literal_msat(self, val: int | str) -> mathsat.msat_term:
        if isinstance(val, int):
            atom = self._idx_to_msat_atom[abs(val) - 1]
            return atom if val > 0 else self._converter.walk_not(None, [atom])
        return self._converter.convert(deserialize_formula(val, self._parser))

    def decode_model_pysmt(self, indices: EncodedModel) -> list[FNode]:
        return [self.decode_literal_pysmt(i) for i in indices]

    def decode_model_msat(self, indices: EncodedModel) -> list[mathsat.msat_term]:
        return [self.decode_literal_msat(i) for i in indices]

    def decode_clause_pysmt(self, clause: EncodedClause) -> FNode:
        known, new = clause
        return self.mgr.Or([self.decode_literal_pysmt(v) for v in (*known, *new)])

    def decode_clause_msat(self, clause: EncodedClause) -> mathsat.msat_term:
        known, new = clause
        return self._converter.walk_or(None, [self.decode_literal_msat(v) for v in (*known, *new)])


def get_converted_atoms(atoms, converter) -> list[mathsat.msat_term]:
    """Returns a list of normalized atoms"""
    return [converter.convert(a) for a in atoms]
