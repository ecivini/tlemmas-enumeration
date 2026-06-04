import pytest
from enumerators.solvers.mathsat_utils import EncodedClause, remove_subsumed_clauses


@pytest.mark.parametrize(
    ("clauses", "expected"),
    [
        pytest.param([], [], id="empty"),
        pytest.param([((1, 2), ())], [((1, 2), ())], id="single"),
        pytest.param([((1,), ()), ((1, 2), ())], [((1,), ())], id="short_subsume_long"),
        pytest.param([((1, 2), ()), ((1, 3), ())], [((1, 2), ()), ((1, 3), ())], id="disjoint"),
        pytest.param([((1, 2), ()), ((1, 2), ())], [((1, 2), ())], id="exact_duplicate"),
        pytest.param([((1, 2), ()), ((1,), ()), ((1, 2, 3), ())], [((1,), ())], id="chain"),
        pytest.param([((1,), ()), ((2,), ()), ((1, 2, 3), ())], [((1,), ()), ((2,), ())], id="two_keepers"),
        pytest.param([((1, 2, 3), ()), ((1, 2), ())], [((1, 2), ())], id="reverse_order_keep_short"),
        pytest.param([((1,), ("x",)), ((1, 2), ())], [((1,), ("x",)), ((1, 2), ())], id="unkowns_different"),
        pytest.param([((1,), ("x",)), ((1, 2), ("x", "y"))], [((1,), ("x",))], id="unknowns_subset"),
    ],
)
def test_remove_subsumed_clauses(clauses: list[EncodedClause], expected: list[EncodedClause]) -> None:
    assert remove_subsumed_clauses(clauses) == expected
