from claimguard.retrieval import BM25, PolicyRetriever, get_index, get_precedents, search_policy, tokens


def test_hybrid_finds_the_right_ncd():
    ix = get_index()
    for q, doc in [("hyperbaric oxygen therapy diabetic wounds", "NCD-20.29"), ("bariatric surgery morbid obesity", "NCD-100.1"),
                   ("CPAP obstructive sleep apnea", "NCD-240.4"), ("cochlear implant hearing loss", "NCD-50.3"),
                   ("external insulin infusion pump", "NCD-280.14")]:
        assert doc in [h["doc_id"] for h in ix.search(q, 3)], q


def test_modes_and_backend():
    r = search_policy("insulin pump", k=3, mode="sparse")
    assert r["backend"].startswith("local_hybrid") and len(r["results"]) == 3
    assert search_policy("insulin pump", k=99)["results"].__len__() <= 8
    assert get_index().search("insulin pump", 2, mode="dense")


def test_bm25_prefers_matching_doc():
    b = BM25([tokens("insulin pump coverage"), tokens("hearing implant")])
    s = b.scores(tokens("insulin"))
    assert s[0] > s[1] == 0


def test_langchain_retriever_returns_documents():
    docs = PolicyRetriever(k=2).invoke("hyperbaric oxygen")
    assert len(docs) == 2 and docs[0].metadata["id"].startswith("NCD-20.29")


def test_precedents_respect_time_and_exclusion():
    hits = get_precedents().search("insulin pump", 5, before_year=2025, exclude_id="MN24-43130")
    assert hits and all(h["year"] < 2025 for h in hits)
    assert "MN24-43130" not in [h["reference_id"] for h in hits]
