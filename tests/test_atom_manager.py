import pytest
from pysmt.fnode import FNode
from pysmt.shortcuts import is_valid
from pysmt.solvers.msat import MSatConverter

from enumerators.formula import is_clause
from enumerators.solvers.mathsat_utils import AtomManager


@pytest.fixture
def a1(x: FNode, y: FNode) -> FNode:
    return x <= y


@pytest.fixture
def a2(x: FNode, z: FNode) -> FNode:
    return x <= z


@pytest.fixture
def a3(y: FNode, z: FNode) -> FNode:
    return y <= z


@pytest.fixture
def mgr_12(a1: FNode, a2: FNode, converter: MSatConverter) -> AtomManager:
    return AtomManager([a1, a2], converter)


@pytest.fixture
def mgr_1(a1: FNode, converter: MSatConverter) -> AtomManager:
    return AtomManager([a1], converter)


@pytest.fixture
def mgr_0(converter: MSatConverter) -> AtomManager:
    return AtomManager([], converter)


# =============================================================================
# encode_literal_pysmt / decode_literal_pysmt
# =============================================================================


@pytest.mark.parametrize("idx, sign", [(1, 1), (1, -1), (2, 1), (2, -1)])
def test_encode_decode_literal_pysmt_round_trip(mgr_12: AtomManager, a1: FNode, a2: FNode, idx: int, sign: int) -> None:
    atom = [a1, a2][idx - 1]
    lit = atom if sign > 0 else ~atom
    assert mgr_12.encode_literal_pysmt(lit) == sign * idx
    assert mgr_12.decode_literal_pysmt(sign * idx) == lit


def test_decode_literal_pysmt_unknown_round_trip(mgr_1: AtomManager, a2: FNode) -> None:
    enc = mgr_1.encode_literal_pysmt(a2)
    assert isinstance(enc, str)
    assert mgr_1.decode_literal_pysmt(enc) == a2


# =============================================================================
# encode_model_pysmt / decode_model_pysmt
# =============================================================================


MODELS_PYSMT = "model", [[], [1], [-2], [1, 2], [-1, -2]]


@pytest.mark.parametrize(*MODELS_PYSMT)
def test_encode_model_pysmt(mgr_12: AtomManager, a1: FNode, a2: FNode, model: list[int]) -> None:
    atoms = [a1, a2]
    pysmt_model = [atoms[abs(lit) - 1] if lit > 0 else ~atoms[abs(lit) - 1] for lit in model]
    encoded = mgr_12.encode_model_pysmt(pysmt_model)
    assert encoded == model
    assert mgr_12.decode_model_pysmt(encoded) == pysmt_model


def test_encode_model_pysmt_asserts_on_unknown(mgr_1: AtomManager, a2: FNode) -> None:
    with pytest.raises(AssertionError):
        mgr_1.encode_model_pysmt([a2])


# =============================================================================
# encode_clause_pysmt / decode_clause_pysmt
# =============================================================================


def test_encode_clause_pysmt_known_only(mgr_12: AtomManager, a1: FNode, a2: FNode) -> None:
    known, new = mgr_12.encode_clause_pysmt(a1 | ~a2)
    assert known == (1, -2)
    assert new == ()


def test_encode_clause_pysmt_single_known_literal(mgr_12: AtomManager, a1: FNode) -> None:
    assert mgr_12.encode_clause_pysmt(a1) == ((1,), ())
    assert mgr_12.encode_clause_pysmt(~a1) == ((-1,), ())


@pytest.mark.parametrize("clause", [1, -1])
def test_encode_clause_pysmt_all_new(mgr_0: AtomManager, a3: FNode, clause: int) -> None:
    lit = a3 if clause >= 0 else ~a3
    known, new = mgr_0.encode_clause_pysmt(lit)
    assert known == ()
    assert len(new) == 1
    assert isinstance(new[0], str)


@pytest.mark.parametrize(
    "clause",
    [
        lambda a1, a2, a3: a1,
        lambda a1, a2, a3: ~a2,
        lambda a1, a2, a3: a1 | a2,
        lambda a1, a2, a3: a1 | ~a2 | a3,
        lambda a1, a2, a3: a1 | (~a2 | a3),
    ],
    ids=["single_pos", "single_neg", "flat_or", "mixed_known_new", "nested_or"],
)
def test_encode_decode_clause_pysmt_round_trip(mgr_12: AtomManager, a1: FNode, a2: FNode, a3: FNode, clause) -> None:
    clause = clause(a1, a2, a3)
    encoded = mgr_12.encode_clause_pysmt(clause)
    decoded = mgr_12.decode_clause_pysmt(encoded)
    assert is_clause(decoded) and is_valid(decoded.Iff(clause))


# =============================================================================
# encode_literal_msat / decode_literal_msat
# =============================================================================


@pytest.mark.parametrize("idx, sign", [(1, 1), (1, -1), (2, 1), (2, -1)])
def test_encode_decode_literal_msat_round_trip(
    mgr_12: AtomManager, converter: MSatConverter, a1: FNode, a2: FNode, idx: int, sign: int
) -> None:
    atom = [a1, a2][idx - 1]
    lit = converter.convert(atom if sign > 0 else ~atom)
    assert mgr_12.encode_literal_msat(lit) == sign * idx
    assert mgr_12.decode_literal_msat(sign * idx) == lit


def test_decode_literal_msat_unknown_round_trip(mgr_1: AtomManager, converter: MSatConverter, a2: FNode) -> None:
    lit = converter.convert(a2)
    enc = mgr_1.encode_literal_msat(lit)
    assert isinstance(enc, str)
    assert mgr_1.decode_literal_msat(enc) == lit


# =============================================================================
# encode_model_msat / decode_model_msat
# =============================================================================


@pytest.mark.parametrize(*MODELS_PYSMT)
def test_encode_model_msat(
    mgr_12: AtomManager, converter: MSatConverter, a1: FNode, a2: FNode, model: list[int]
) -> None:
    atoms = [a1, a2]
    msat_model = [converter.convert(atoms[abs(lit) - 1] if lit > 0 else ~atoms[abs(lit) - 1]) for lit in model]
    encoded = mgr_12.encode_model_msat(msat_model)
    assert encoded == model
    assert mgr_12.decode_model_msat(encoded) == msat_model


def test_encode_model_msat_asserts_on_unknown(mgr_1: AtomManager, converter: MSatConverter, a2: FNode) -> None:
    with pytest.raises(AssertionError):
        mgr_1.encode_model_msat([converter.convert(a2)])


# =============================================================================
# encode_clause_msat / decode_clause_msat
# =============================================================================


def test_encode_clause_msat_known_only(mgr_12: AtomManager, converter: MSatConverter, a1: FNode, a2: FNode) -> None:
    known, new = mgr_12.encode_clause_msat(converter.convert(a1 | ~a2))
    assert known == (1, -2)
    assert new == ()


def test_encode_clause_msat_single_known_literal(mgr_12: AtomManager, converter: MSatConverter, a1: FNode) -> None:
    assert mgr_12.encode_clause_msat(converter.convert(a1)) == ((1,), ())
    assert mgr_12.encode_clause_msat(converter.convert(~a1)) == ((-1,), ())


@pytest.mark.parametrize("clause", [1, -1])
def test_encode_clause_msat_all_new(mgr_0: AtomManager, converter: MSatConverter, a3: FNode, clause: int) -> None:
    lit = converter.convert(a3 if clause >= 0 else ~a3)
    known, new = mgr_0.encode_clause_msat(lit)
    assert known == ()
    assert len(new) == 1
    assert isinstance(new[0], str)


@pytest.mark.parametrize(
    "clause",
    [
        lambda a1, a2, a3: a1,
        lambda a1, a2, a3: ~a2,
        lambda a1, a2, a3: a1 | a2,
        lambda a1, a2, a3: a1 | ~a2 | a3,
        lambda a1, a2, a3: a1 | (~a2 | a3),
    ],
    ids=["single_pos", "single_neg", "flat_or", "mixed_known_new", "nested_or"],
)
def test_encode_decode_clause_msat_round_trip(
    mgr_12: AtomManager, converter: MSatConverter, a1: FNode, a2: FNode, a3: FNode, clause
) -> None:
    clause = clause(a1, a2, a3)
    msat_clause = converter.convert(clause)
    encoded = mgr_12.encode_clause_msat(msat_clause)
    msat_decoded = mgr_12.decode_clause_msat(encoded)
    decoded = converter.back(msat_decoded)

    assert is_clause(decoded) and is_valid(decoded.Iff(clause))


# =============================================================================
# Properties
# =============================================================================


def test_atoms_property(mgr_12: AtomManager, a1: FNode, a2: FNode) -> None:
    assert mgr_12.atoms == [a1, a2]


def test_msat_env_property(mgr_1: AtomManager) -> None:
    assert mgr_1.msat_env is not None
