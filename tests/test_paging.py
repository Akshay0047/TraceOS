"""Page replacement, including Belady's anomaly for FIFO."""

from traceos.paging import compare_paging, fifo, lru, optimal

BELADY = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]


def test_fifo_belady_anomaly():
    assert fifo(BELADY, 3) == 9
    assert fifo(BELADY, 4) == 10


def test_lru_and_optimal_on_belady_string():
    assert lru(BELADY, 3) == 10
    assert optimal(BELADY, 3) == 7


def test_optimal_is_a_lower_bound():
    results = {item.name: item.faults for item in compare_paging(BELADY, 3)}
    assert results["Optimal"] <= results["FIFO"]
    assert results["Optimal"] <= results["LRU"]
