from io import StringIO

from pysmt.shortcuts import And
from pysmt.fnode import FNode
from pysmt.smtlib.parser import SmtLibParser
from pysmt.smtlib.script import smtlibscript_from_formula


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


def formula_to_conjuncts(formula: FNode) -> list[FNode]:
    """Return the conjuncts of a formula as a flat list."""
    if formula.is_true():
        return []
    if formula.is_and():
        return list(formula.args())
    return [formula]


def serialize_conjunction(formulas: list[FNode]) -> str:
    """Serialize a conjunction of formulas to SMT-LIB text."""
    return serialize_formula(And(formulas))


def deserialize_conjunction(formula_str: str, parser: SmtLibParser) -> list[FNode]:
    """Deserialize SMT-LIB text and flatten conjunctions."""
    return formula_to_conjuncts(deserialize_formula(formula_str, parser))
