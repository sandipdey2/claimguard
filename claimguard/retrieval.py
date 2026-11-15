"""Hybrid retrieval over CMS coverage policy (NCD, optional LCD) and IMR precedent search.

Local default: BM25 (sparse) + LSA vectors in FAISS (dense), fused with reciprocal-rank fusion (RRF).
Azure: when AZURE_SEARCH_ENDPOINT/INDEX are set, ``search_policy`` sends a hybrid (keyword + vector) query to Azure
AI Search with the same chunk ids, and falls back to the local index on any error (the fallback is logged).
``PolicyRetriever`` is a LangChain ``BaseRetriever`` so the agents and notebooks can use it like any retriever.
"""
from __future__ import annotations

import json
import re
import threading
from collections import Counter
from functools import lru_cache

import numpy as np
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .config import secret
from .data import lcd_raw_path, load_imr, load_imr_findings, load_ncd

TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
STOP = set("the a an of and or to in for on with by is are be as at from that this it its was were not no any all may can will which "
           "such other than when under into these those has have had been their there must only also if per each".split())
CHUNK_CHARS = 1200


def tokens(text: str) -> list[str]:
    return [t for t in TOKEN.findall((text or "").lower()) if t not in STOP and len(t) > 1]


# ----------------------------------------------------------------------------- corpus
def ncd_chunks() -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=0, separators=["\n\n", "\n- ", "\n", ". ", " "])
    out = []
    for r in load_ncd().itertuples():
        body = "\n\n".join(t for t in [r.item_service, r.indications_limitations] if t)
        if not body.strip():
            body = r.title
        for i, piece in enumerate(splitter.split_text(body), start=1):
            out.append({"id": f"NCD-{r.ncd_id}:{i}", "doc_id": f"NCD-{r.ncd_id}", "doc_type": "NCD", "title": r.title,
                        "text": piece.strip(), "url": r.url, "effective": r.effective, "version": int(r.version)})
    return out


def lcd_chunks(limit_chars: int = 6000) -> list[dict]:
    """Optional: LCD 'Covered Indications' narrative, indexed locally only when CG_INCLUDE_LCD=1 and data/raw/current_lcd.zip exists.
    5-digit CPT-like codes are masked; LCD text is never committed or redistributed."""
    p = lcd_raw_path()
    if p is None or secret("CG_INCLUDE_LCD") != "1":
        return []
    import io
    import zipfile

    import pandas as pd

    from .data import html_to_text
    z = zipfile.ZipFile(p)
    inner = zipfile.ZipFile(io.BytesIO(z.read("current_lcd_csv.zip")))
    d = pd.read_csv(io.BytesIO(inner.read("lcd.csv")), encoding="latin-1", low_memory=False)
    d = d[d.status == "A"]
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=0)
    out = []
    for r in d.itertuples():
        text = re.sub(r"\b\d{4}[0-9A-Z]\b", "[code]", html_to_text(r.indication))[:limit_chars]
        for i, piece in enumerate(splitter.split_text(text), start=1):
            lid = f"L{r.lcd_id}"
            out.append({"id": f"LCD-{lid}:{i}", "doc_id": f"LCD-{lid}", "doc_type": "LCD", "title": str(r.title), "text": piece.strip(),
                        "url": f"https://www.cms.gov/medicare-coverage-database/view/lcd.aspx?lcdid={r.lcd_id}", "effective": str(r.rev_eff_date)[:10],
                        "version": int(r.lcd_version)})
    return out


# ----------------------------------------------------------------------------- local hybrid index
class BM25:
    """Okapi BM25 over a sparse term matrix (vectorised; k1=1.4, b=0.75)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75) -> None:
        from scipy import sparse
        self.vocab: dict[str, int] = {}
        rows, cols, vals = [], [], []
        for i, d in enumerate(docs):
            for t, f in Counter(d).items():
                rows.append(i)
                cols.append(self.vocab.setdefault(t, len(self.vocab)))
                vals.append(f)
        tf = sparse.csr_matrix((vals, (rows, cols)), shape=(len(docs), max(1, len(self.vocab))), dtype=float)
        n = len(docs)
        dl = np.asarray(tf.sum(axis=1)).ravel()
        avg = float(dl.mean()) if n else 1.0
        df = np.bincount(tf.indices, minlength=tf.shape[1])
        self.idf = np.log(1 + (n - df + 0.5) / (df + 0.5))
        tf = tf.tocoo()
        denom = tf.data + k1 * (1 - b + b * dl[tf.row] / avg)
        w = tf.data * (k1 + 1) / denom
        self.W = sparse.csc_matrix((w, (tf.row, tf.col)), shape=tf.shape)

    def scores(self, q: list[str]) -> np.ndarray:
        ids = [self.vocab[t] for t in set(q) if t in self.vocab]
        if not ids:
            return np.zeros(self.W.shape[0])
        return np.asarray(self.W[:, ids] @ self.idf[ids]).ravel()


class HybridIndex:
    def __init__(self, chunks: list[dict]) -> None:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize
        self.chunks = chunks
        self.by_id = {c["id"]: c for c in chunks}
        texts = [f"{c['title']}. {c['title']}. {c['text']}" for c in chunks]
        self.bm25 = BM25([tokens(t) for t in texts])
        self.tfidf = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=1, stop_words="english")
        X = self.tfidf.fit_transform(texts)
        dim = min(256, X.shape[1] - 1, X.shape[0] - 1)
        self.svd = TruncatedSVD(dim, random_state=42).fit(X)
        self._normalize = normalize
        self.V = normalize(self.svd.transform(X)).astype("float32")
        self._build_faiss()

    def _build_faiss(self) -> None:
        try:
            import faiss
            self.faiss = faiss.IndexFlatIP(self.V.shape[1])
            self.faiss.add(self.V)
            self.backend = "faiss IndexFlatIP (cosine on L2-normalised LSA vectors)"
        except Exception:                      # pragma: no cover - faiss missing
            self.faiss, self.backend = None, "numpy cosine"  # type: ignore[assignment]

    def __getstate__(self) -> dict:            # the FAISS index is rebuilt from V after unpickling
        st = dict(self.__dict__)
        st["faiss"] = None
        return st

    def __setstate__(self, st: dict) -> None:
        self.__dict__.update(st)
        self._build_faiss()

    def embed(self, q: str) -> np.ndarray:
        return self._normalize(self.svd.transform(self.tfidf.transform([q]))).astype("float32")

    def search(self, query: str, k: int = 5, mode: str = "hybrid", doc_type: str | None = None) -> list[dict]:
        n = len(self.chunks)
        depth = min(n, 50)
        rank_lists = []
        if mode in ("hybrid", "sparse"):
            s = self.bm25.scores(tokens(query))
            rank_lists.append([int(i) for i in np.argsort(-s)[:depth] if s[i] > 0])
        if mode in ("hybrid", "dense"):
            qv = self.embed(query)
            if self.faiss is not None:
                _, idx = self.faiss.search(qv, depth)
                rank_lists.append([int(i) for i in idx[0] if i >= 0])
            else:
                rank_lists.append([int(i) for i in np.argsort(-(self.V @ qv[0]))[:depth]])
        fused: dict[int, float] = {}
        for rl in rank_lists:
            for r, i in enumerate(rl):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + r + 1)        # RRF, k=60
        order = sorted(fused, key=lambda i: -fused[i])
        out = []
        for i in order:
            c = self.chunks[i]
            if doc_type and c["doc_type"] != doc_type:
                continue
            out.append({**c, "score": round(fused[i], 5)})
            if len(out) >= k:
                break
        return out


_lock = threading.Lock()


@lru_cache(maxsize=1)
def get_index() -> HybridIndex:
    """Built once per process and cached on disk (data/runtime), keyed by the NCD snapshot checksum and the LCD flag."""
    import joblib
    import sklearn

    from .config import RUNTIME
    from .data import manifest
    with _lock:
        key = manifest()["snapshot_files"]["ncd.parquet"]["sha256"][:12] + ("_lcd" if secret("CG_INCLUDE_LCD") == "1" else "")
        path = RUNTIME / f"policy_index_{key}_{sklearn.__version__}.joblib"
        if path.exists():
            try:
                ix = joblib.load(path)
                if ix.faiss is None or ix.faiss.ntotal == len(ix.chunks):
                    return ix
            except Exception:
                pass
        ix = HybridIndex(ncd_chunks() + lcd_chunks())
        try:
            RUNTIME.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            joblib.dump(ix, tmp)
            tmp.replace(path)
        except Exception:
            pass
        return ix


def corpus_ids() -> set[str]:
    return set(get_index().by_id) | {c["doc_id"] for c in get_index().chunks}


# ----------------------------------------------------------------------------- Azure AI Search adapter
def azure_search(query: str, k: int, vector: list[float] | None = None) -> list[dict]:
    """Hybrid query (BM25 keyword + vector, RRF inside Azure AI Search; semantic ranker if AZURE_SEARCH_SEMANTIC_CONFIG is set)."""
    import httpx
    endpoint, index = secret("AZURE_SEARCH_ENDPOINT"), secret("AZURE_SEARCH_INDEX")
    key = secret("AZURE_SEARCH_API_KEY")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["api-key"] = key
    else:
        from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
        headers["Authorization"] = "Bearer " + DefaultAzureCredential().get_token("https://search.azure.com/.default").token
    body: dict = {"search": query, "top": k, "select": "id,doc_id,doc_type,title,text,url,effective,version"}
    if vector is not None:
        body["vectorQueries"] = [{"kind": "vector", "vector": vector, "fields": "embedding", "k": k}]
    sem = secret("AZURE_SEARCH_SEMANTIC_CONFIG")
    if sem:
        body.update({"queryType": "semantic", "semanticConfiguration": sem})
    r = httpx.post(f"{(endpoint or '').rstrip('/')}/indexes/{index}/docs/search?api-version=2024-07-01", headers=headers, json=body, timeout=15)
    r.raise_for_status()
    return [{**{f: d.get(f) for f in ("id", "doc_id", "doc_type", "title", "text", "url", "effective", "version")},
             "score": d.get("@search.rerankerScore") or d.get("@search.score")} for d in r.json().get("value", [])]


def search_policy(query: str, k: int = 5, mode: str = "hybrid", doc_type: str | None = None) -> dict:
    k = max(1, min(int(k), 8))
    if secret("AZURE_SEARCH_ENDPOINT") and secret("AZURE_SEARCH_INDEX"):
        try:
            vec = get_index().embed(query)[0].tolist()
            hits = azure_search(query, k, vec)
            return {"backend": "azure_ai_search", "results": hits}
        except Exception as exc:
            return {"backend": "local_hybrid (azure_ai_search failed: " + type(exc).__name__ + ")",
                    "results": get_index().search(query, k, mode, doc_type)}
    return {"backend": f"local_hybrid bm25+{get_index().backend} rrf", "results": get_index().search(query, k, mode, doc_type)}


class PolicyRetriever(BaseRetriever):
    """LangChain retriever over the coverage-policy corpus (local hybrid or Azure AI Search)."""
    k: int = 5
    mode: str = "hybrid"

    def _get_relevant_documents(self, query: str, *, run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        res = search_policy(query, self.k, self.mode)
        return [Document(page_content=h["text"], metadata={kk: v for kk, v in h.items() if kk != "text"} | {"backend": res["backend"]})
                for h in res["results"]]


# ----------------------------------------------------------------------------- IMR precedent search
class PrecedentIndex:
    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        df = load_imr()
        self.df = df.reset_index(drop=True)
        text = (df.request_text.fillna("") + " " + df.TreatmentSubCategory + " " + df.DiagnosisSubCategory).str.lower()
        self.vec = TfidfVectorizer(sublinear_tf=True, ngram_range=(1, 2), min_df=2, stop_words="english")
        self.X = self.vec.fit_transform(text)

    def search(self, query: str, k: int = 5, before_year: int | None = None, exclude_id: str | None = None,
               treatment_category: str | None = None) -> list[dict]:
        q = self.vec.transform([query.lower()])
        sims = (self.X @ q.T).toarray().ravel()
        mask = np.ones(len(sims), dtype=bool)
        if before_year is not None:
            mask &= (self.df.ReportYear < int(before_year)).to_numpy()
        if exclude_id:
            mask &= (self.df.ReferenceID != exclude_id).to_numpy()
        if treatment_category:
            mask &= (self.df.TreatmentCategory == treatment_category).to_numpy()
        sims = np.where(mask, sims + 0.01 * (self.df.ReportYear.to_numpy() - 2001) / 25, -1)   # tiny recency tie-break
        idx = [int(i) for i in np.argsort(-sims)[: k * 3] if sims[i] > 0.05][:k]
        findings = load_imr_findings()
        out = []
        for i in idx:
            r = self.df.iloc[i]
            f = findings.get(r.ReferenceID)
            out.append({"reference_id": r.ReferenceID, "year": int(r.ReportYear), "determination": r.Determination,
                        "treatment": f"{r.TreatmentCategory} / {r.TreatmentSubCategory}", "diagnosis": f"{r.DiagnosisCategory} / {r.DiagnosisSubCategory}",
                        "type": r.Type, "request": r.request_text, "similarity": round(float(sims[i]), 3),
                        "findings_excerpt": (f[:600] + "...") if f and len(f) > 600 else f})
        return out


@lru_cache(maxsize=1)
def get_precedents() -> PrecedentIndex:
    return PrecedentIndex()


def to_json(obj) -> str:
    return json.dumps(obj, indent=1, default=str)
