"""Policy search tests — pure keyword/BM25, no LLM calls, runs offline."""
from src.policy_search import PolicySearch

_search = None


def get_search() -> PolicySearch:
    global _search
    if _search is None:
        _search = PolicySearch()
    return _search


def test_index_builds_with_chunks_from_all_five_docs():
    ps = get_search()
    doc_ids = {c.doc_id for c in ps.chunks}
    assert {"RW-POL-01", "RW-POL-02", "RW-POL-03", "RW-POL-04", "RW-POL-05"} <= doc_ids


def test_annexure_transcriptions_are_indexed_and_searchable():
    ps = get_search()
    results = ps.search("tier benefits grace period gold")
    assert any("Annexure A" in c.title for c, _ in results)


def test_refund_search_surfaces_the_v1_slab_table():
    ps = get_search()
    results = ps.search("refund schedule hours before pickup cancellation", top_k=10)
    matched = [c for c, _ in results if c.doc_id == "RW-POL-02" and c.section == "1.1"]
    assert matched, "expected RW-POL-02 section 1.1 (the actual refund slab table) in results"


def test_late_fee_search_surfaces_gold_grace_rule():
    ps = get_search()
    results = ps.search("late fee grace period gold tier", top_k=5)
    assert any(c.doc_id == "RW-POL-04" for c, _ in results)


def test_battery_fee_search_surfaces_the_rule_section():
    ps = get_search()
    results = ps.search("low battery charging fee percent", top_k=5)
    assert any(c.doc_id == "RW-POL-04" and c.section == "2" for c, _ in results)


def test_version_aware_search_prefers_the_applicable_doc():
    ps = get_search()
    results = ps.search_for_version("refund for cancelling my booking", "RW-POL-03", top_k=5)
    assert results[0][0].doc_id == "RW-POL-03"


def test_version_aware_search_without_preference_returns_both_versions():
    ps = get_search()
    results = ps.search_for_version("refund for cancelling my booking", None, top_k=10)
    doc_ids = {c.doc_id for c, _ in results}
    assert "RW-POL-02" in doc_ids or "RW-POL-03" in doc_ids


def test_search_is_empty_for_nonsense_query():
    ps = get_search()
    results = ps.search("zzzqqxxnonexistentpolicyterm")
    assert results == []
