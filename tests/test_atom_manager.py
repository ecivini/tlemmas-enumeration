from pysmt.fnode import FNode
from pysmt.shortcuts import is_valid
import pytest

from enumerators.solvers.mathsat_utils import AtomManager


@pytest.fixture
def a1(x, y) -> FNode:
    return x < y


@pytest.fixture
def a2(x, z) -> FNode:
    return x < z


@pytest.fixture
def a3(y, z) -> FNode:
    return y < z


def test_encode_decode_known_literals(a1, a2):
    mgr = AtomManager([a1, a2])

    assert mgr.encode_literal(a1) == 1
    assert mgr.encode_literal(~a1) == -1
    assert mgr.decode_literal(1) == a1
    assert mgr.decode_literal(-1) == ~a1


def test_encode_decode_model(a1, a2):
    mgr = AtomManager([a1, a2])

    model = [a1, ~a2]

    encoded = mgr.encode_model(model)

    assert encoded == [1, -2]
    assert mgr.decode_model(encoded) == model


def test_encode_clause_splits_known_and_unknown_atoms(a1, a2, a3):
    mgr = AtomManager([a1, a2])

    clause = a1 | ~a2 | ~a3

    known, new = mgr.encode_clause(clause)

    assert set(known) == {1, -2}
    assert len(new) == 1
    assert is_valid(mgr.decode_clause((known, new)).Iff(clause))


def test_round_trip_for_serialized_unknown_literal(a1, a2):
    mgr = AtomManager([a1])

    unknown = a2
    encoded = mgr.encode_literal(unknown)

    assert isinstance(encoded, str)
    assert mgr.decode_literal(encoded) == unknown
