import pytest
from pysmt.fnode import FNode
from pysmt.shortcuts import FALSE, is_valid

from enumerators.solvers.mathsat_utils import AtomManager


@pytest.fixture
def a1(x: FNode, y: FNode) -> FNode:
    return x < y


@pytest.fixture
def a2(x: FNode, z: FNode) -> FNode:
    return x < z


@pytest.fixture
def a3(y: FNode, z: FNode) -> FNode:
    return y < z


def test_encode_decode_known_literals(a1: FNode, a2: FNode) -> None:
    mgr = AtomManager([a1, a2])

    assert mgr.encode_literal(a1) == 1
    assert mgr.encode_literal(~a1) == -1
    assert mgr.decode_literal(1) == a1
    assert mgr.decode_literal(-1) == ~a1


def test_encode_decode_unknown_literal_round_trip(a1: FNode, a2: FNode) -> None:
    mgr = AtomManager([a1])

    unknown = ~a2
    encoded = mgr.encode_literal(unknown)

    assert isinstance(encoded, str)
    assert mgr.decode_literal(encoded) == unknown


def test_encode_decode_model(a1: FNode, a2: FNode) -> None:
    mgr = AtomManager([a1, a2])

    for model in ([], [a1], [~a1, a2], [~a1, ~a2]):
        encoded = mgr.encode_model(model)

        assert encoded == [mgr.encode_literal(lit) for lit in model]
        assert mgr.decode_model(encoded) == model


def test_encode_decode_empty_inputs() -> None:
    mgr = AtomManager([])

    assert mgr.encode_model([]) == []
    assert mgr.decode_model([]) == []
    assert mgr.decode_clause(([], [])) == FALSE()


def test_encode_clause_round_trip(a1: FNode, a2: FNode, a3: FNode) -> None:
    mgr = AtomManager([a1, a2])

    clause = a1 | ~a2 | ~a3
    known, new = mgr.encode_clause(clause)

    assert known == [-2, 1]
    assert new == [mgr.encode_literal(~a3)]
    assert isinstance(new[0], str)
    assert is_valid(mgr.decode_clause((known, new)).Iff(clause))
