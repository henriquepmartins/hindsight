"""Content-addressed openfda blocks, and the empty-dict distinction.

Two properties carry the weight here. The key must depend on a block's content
and nothing else — not key order, not insertion order, not the run — because
`dim_openfda` doubles quietly if it doesn't. And an empty block must stay
distinguishable from an absent one, which is the bug (L-005) that these tests
exist to keep dead.
"""

import pytest

from hindsight import normalize as n
from hindsight.normalize import KeyCollision, OpenfdaDimension, key


ASPIRIN = {"brand_name": ["ASPIRIN"], "unii": ["R16CO5Y76E"]}
IBUPROFEN = {"brand_name": ["ADVIL"], "unii": ["WK2XYI10QM"]}


@pytest.fixture
def dimension():
    return OpenfdaDimension()


# --- the key is the content -------------------------------------------------


def test_key_ignores_the_order_the_block_was_written_in():
    assert key({"a": ["1"], "b": ["2"]}) == key({"b": ["2"], "a": ["1"]})


def test_key_ignores_key_order_at_every_depth():
    """`sort_keys=True` recurses. If it didn't, nested reordering would split
    one product into two dimension rows."""
    deep = {"outer": {"a": ["1"], "b": ["2"]}, "unii": ["X"]}
    shuffled = {"unii": ["X"], "outer": {"b": ["2"], "a": ["1"]}}

    assert key(deep) == key(shuffled)


def test_key_is_pinned_not_merely_stable():
    """A literal, so that changing the separators, the sort, or the encoding
    fails here rather than silently re-keying every dimension row ever written."""
    assert key(ASPIRIN) == "59556fc197ca0cfa"
    assert key({}) == "bf21a9e8fbc5a384"


def test_key_is_the_documented_width():
    assert len(key(ASPIRIN)) == n.KEY_LENGTH


def test_different_blocks_get_different_keys():
    assert key(ASPIRIN) != key(IBUPROFEN)


# --- absent is not empty ----------------------------------------------------


def test_an_empty_block_is_a_real_block_with_a_real_key():
    assert key({}) is not None


def test_an_absent_block_has_no_key():
    assert key(None) is None


def test_the_falsy_test_is_the_bug_this_rule_exists_for():
    """`if block` instead of `if block is not None` collapses `openfda: {}` into
    absent — 492 mismatches in the spike, and 507 blocks in this partition that
    would follow. Shown side by side rather than committed and waited on."""
    empty = {}

    assert key(empty) is not None
    assert (key(empty) if empty else None) is None


# --- first-sight emission ---------------------------------------------------


def test_a_block_is_emitted_the_first_time_and_not_again(dimension):
    first_key, first_row = dimension.add(ASPIRIN)
    second_key, second_row = dimension.add(ASPIRIN)

    assert first_row is ASPIRIN
    assert second_row is None
    assert first_key == second_key == key(ASPIRIN)


def test_a_reordered_block_is_the_same_block(dimension):
    dimension.add({"a": ["1"], "b": ["2"]})
    _, row = dimension.add({"b": ["2"], "a": ["1"]})

    assert row is None
    assert len(dimension) == 1


def test_every_distinct_block_is_emitted(dimension):
    emitted = [dimension.add(b)[1] for b in (ASPIRIN, IBUPROFEN, ASPIRIN, {})]

    assert emitted == [ASPIRIN, IBUPROFEN, None, {}]
    assert len(dimension) == 3


def test_an_absent_block_costs_the_caller_no_branch(dimension):
    """(None, None) is what lets T9's write loop stay a straight line, which is
    where the L-005 test would otherwise have to be repeated by hand."""
    assert dimension.add(None) == (None, None)
    assert len(dimension) == 0


# --- what the dimension is allowed to remember ------------------------------


def test_the_dimension_holds_digests_not_blocks(dimension):
    """The whole memory argument, pinned. The spike kept the blocks and that is
    the version that does not survive 1,767 partitions."""
    for block in (ASPIRIN, IBUPROFEN, {}):
        dimension.add(block)

    assert set(vars(dimension)) == {"_digests"}
    assert all(isinstance(value, str) for value in dimension._digests.values())


def test_a_truncation_collision_raises_rather_than_merging(monkeypatch, dimension):
    """Two blocks, one key. Forced, because a real sha1 truncation collision is
    not something a test can produce — but a silent merge would hand every drug
    row at that key another product's enrichment."""
    monkeypatch.setattr(
        n, "_digest", lambda block: "f" * n.KEY_LENGTH + ("1" if block else "2") * 24
    )

    dimension.add(ASPIRIN)

    with pytest.raises(KeyCollision, match="truncate to 'ffffffffffffffff'"):
        dimension.add({})


def test_the_same_block_under_a_shared_key_is_not_a_collision(monkeypatch, dimension):
    monkeypatch.setattr(n, "_digest", lambda block: "f" * 40)

    dimension.add(ASPIRIN)

    assert dimension.add(IBUPROFEN)[1] is None
