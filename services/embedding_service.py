"""
embedding_service.py
--------------------
Vrai RAG vectoriel : chunking des fichiers, generation d'embeddings et
indexation dans Chroma.

Pipeline :
  1. Les fichiers du depot sont decoupes en chunks :
       - fichiers .py  -> extraction AST (fonctions/classes/docstrings)
       - autres        -> decoupage textuel par blocs (fallback)
  2. Chaque chunk est transforme en vecteur (embeddings).
  3. Les vecteurs sont stockes dans une collection Chroma persistante,
     une collection par depot (owner/repo@branch).
  4. La recherche se fait par similarite vectorielle (similarity_search).

Providers d'embeddings :
  - "local"      : sentence-transformers (gratuit, hors ligne, defaut).
  - "openrouter" : API OpenRouter (necessite OPENROUTER_API_KEY).

Re-indexation :
  - Chaque collection stocke le SHA du dernier commit indexe.
  - Si le SHA change, l'index est reconstruit (voir main.py).
"""

import hashlib
import os
import threading
from typing import Iterable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config.config import (
    CHROMA_PERSIST_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_MODEL_LOCAL,
    EMBEDDING_MODEL_REMOTE,
    EMBEDDING_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_API_BASE,
    RAG_TOP_K,
)
from services.code_parser import parse_file

# ─── Verrous (Chroma n'est pas thread-safe en ecriture) ──────────────────────
_index_lock = threading.Lock()
_client_lock = threading.Lock()

_chroma_client = None


# ─── Decoupage des fichiers ──────────────────────────────────────────────────

def _splitter() -> RecursiveCharacterTextSplitter:
    """
    Splitter adapte au code : coupe en priorite sur les frontieres de classes
    et de fonctions avant de tomber sur les sauts de ligne.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=[
            "\nclass ", "\ndef ", "\npublic ", "\nprivate ", "\nfunc ",
            "\n\n", "\n", ". ", " ", "",
        ],
    )


def chunk_files(files_content: dict[str, str]) -> list[Document]:
    """
    Decoupe un ensemble de fichiers en chunks prets a etre indexes.

    Strategie par fichier :
      1. Extraction structurelle via `code_parser.parse_file` :
         - .py  -> fonctions / classes / methodes / docstrings (AST)
         - autres -> blocs logiques (class / function / method)
      2. Si un symbole extrait depasse CHUNK_SIZE, il est re-decoupe par le
         splitter textuel pour respecter la taille cible.
      3. Si aucun symbole n'est extrait, fallback sur le decoupage textuel brut.

    Args:
        files_content: { chemin_fichier: contenu_texte }

    Returns:
        Liste de Documents LangChain avec metadonnees
        (source, chunk_index, symbol, kind, start_line, end_line).
    """
    splitter = _splitter()
    documents: list[Document] = []

    for path, content in files_content.items():
        if not content or not content.strip():
            continue

        units = parse_file(path, content)

        # Fallback : aucun symbole extrait -> decoupage textuel brut.
        if not units:
            units = [{
                "content": content,
                "symbol": "<file>",
                "kind": "block",
                "start": 1,
                "end": len(content.splitlines()),
            }]

        chunk_index = 0
        for unit in units:
            text = unit["content"]
            # Un symbole trop gros est re-decoupe pour rester dans la cible.
            pieces = (
                splitter.split_text(text)
                if len(text) > CHUNK_SIZE
                else [text]
            )
            for piece in pieces:
                if not piece.strip():
                    continue
                documents.append(
                    Document(
                        page_content=piece,
                        metadata={
                            "source": path,
                            "chunk_index": chunk_index,
                            "symbol": unit.get("symbol", "<file>"),
                            "kind": unit.get("kind", "block"),
                            "start_line": unit.get("start", 1),
                            "end_line": unit.get("end", 1),
                        },
                    )
                )
                chunk_index += 1

    return documents


# ─── Providers d'embeddings ──────────────────────────────────────────────────

class _LocalEmbeddings(Embeddings):
    """
    Embeddings gratuits via sentence-transformers.
    Le modele est charge paresseusement (au premier appel) pour ne pas
    ralentir le demarrage du service.
    """

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    print(f"[embedding_service] Chargement du modele local '{self._model_name}'...")
                    self._model = SentenceTransformer(self._model_name)
                    print("[embedding_service] Modele local pret.")
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._get_model().encode(
            texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True
        )
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._get_model().encode(
            [text], show_progress_bar=False, normalize_embeddings=True
        )[0]
        return vector.tolist()


class _OpenRouterEmbeddings(Embeddings):
    """
    Embeddings via l'API OpenRouter (compatible OpenAI).
    Utilise uniquement si EMBEDDING_PROVIDER=openrouter.
    """

    def __init__(self, model_name: str):
        from openai import OpenAI

        if not OPENAI_API_KEY:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openrouter necessite OPENROUTER_API_KEY dans le .env."
            )
        self._model_name = model_name
        self._client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model_name, input=texts)
        return [item.embedding for item in response.data]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # L'API limite la taille des lots : on decoupe par paquets de 64.
        vectors: list[list[float]] = []
        for i in range(0, len(texts), 64):
            vectors.extend(self._embed(texts[i:i + 64]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


_embeddings_cache: dict[str, Embeddings] = {}


def get_embeddings() -> Embeddings:
    """
    Retourne l'implementation d'embeddings configuree (singleton par provider).
    """
    provider = EMBEDDING_PROVIDER
    if provider not in _embeddings_cache:
        if provider == "openrouter":
            _embeddings_cache[provider] = _OpenRouterEmbeddings(EMBEDDING_MODEL_REMOTE)
        else:
            _embeddings_cache[provider] = _LocalEmbeddings(EMBEDDING_MODEL_LOCAL)
    return _embeddings_cache[provider]


# ─── Client Chroma ───────────────────────────────────────────────────────────

def _get_client():
    """Client Chroma persistant (singleton)."""
    global _chroma_client
    if _chroma_client is None:
        with _client_lock:
            if _chroma_client is None:
                import chromadb
                from chromadb.config import Settings

                os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
                _chroma_client = chromadb.PersistentClient(
                    path=CHROMA_PERSIST_DIR,
                    settings=Settings(anonymized_telemetry=False),
                )
    return _chroma_client


def _collection_name(repo_key: str) -> str:
    """
    Nom de collection Chroma valide (3-63 caracteres, alphanumerique).
    On y ajoute un hash court pour eviter les collisions entre depots.
    """
    digest = hashlib.sha1(repo_key.encode("utf-8")).hexdigest()[:10]
    safe = "".join(c if c.isalnum() else "-" for c in repo_key.lower())
    safe = safe.strip("-")[:40] or "repo"
    return f"{safe}-{digest}"


def _get_collection(repo_key: str):
    return _get_client().get_or_create_collection(
        name=_collection_name(repo_key),
        metadata={"hnsw:space": "cosine", "repo_key": repo_key},
    )


# ─── Indexation ──────────────────────────────────────────────────────────────

def index_repo(
    repo_key: str,
    files_content: dict[str, str],
    commit_sha: str | None = None,
) -> int:
    """
    (Re)construit l'index vectoriel d'un depot.

    Args:
        repo_key:     Identifiant du depot, ex. "owner/repo@main".
        files_content: { chemin: contenu } des fichiers a indexer.
        commit_sha:   SHA du commit indexe (stocke pour detecter les changements).

    Returns:
        Nombre de chunks indexes.
    """
    documents = chunk_files(files_content)
    if not documents:
        return 0

    embeddings = get_embeddings()
    vectors = embeddings.embed_documents([d.page_content for d in documents])

    ids = [
        hashlib.sha1(f"{repo_key}:{d.metadata['source']}:{d.metadata['chunk_index']}".encode()).hexdigest()
        for d in documents
    ]

    with _index_lock:
        client = _get_client()
        # Reconstruit l'index de zero pour eviter les chunks obsoletes.
        try:
            client.delete_collection(_collection_name(repo_key))
        except Exception:
            pass
        collection = _get_collection(repo_key)
        collection.add(
            ids=ids,
            embeddings=vectors,
            documents=[d.page_content for d in documents],
            metadatas=[d.metadata for d in documents],
        )
        if commit_sha:
            collection.modify(metadata={
                "hnsw:space": "cosine",
                "repo_key": repo_key,
                "commit_sha": commit_sha,
            })

    print(f"[embedding_service] {len(documents)} chunks indexes pour {repo_key} (commit {commit_sha or 'n/a'}).")
    return len(documents)


def get_indexed_commit(repo_key: str) -> str | None:
    """Retourne le SHA du commit actuellement indexe, ou None si absent."""
    try:
        collection = _get_collection(repo_key)
        return (collection.metadata or {}).get("commit_sha")
    except Exception:
        return None


def is_indexed(repo_key: str) -> bool:
    """Indique si une collection non vide existe pour ce depot."""
    try:
        return _get_collection(repo_key).count() > 0
    except Exception:
        return False


# ─── Recherche vectorielle ───────────────────────────────────────────────────

def similarity_search(
    repo_key: str,
    query: str,
    top_k: int = RAG_TOP_K,
) -> list[dict]:
    """
    Recherche les chunks les plus proches de la requete dans l'index du depot.

    Args:
        repo_key: Identifiant du depot, ex. "owner/repo@main".
        query:    Question de l'utilisateur.
        top_k:    Nombre de chunks a remonter.

    Returns:
        Liste de { "path", "content", "score", "symbol", "kind", "start_line",
        "end_line" } tries par pertinence decroissante.
        Liste vide si l'index n'existe pas.
    """
    if not is_indexed(repo_key):
        return []

    query_vector = get_embeddings().embed_query(query)
    collection = _get_collection(repo_key)
    result = collection.query(
        query_embeddings=[query_vector],
        n_results=min(top_k, max(collection.count(), 1)),
        include=["documents", "metadatas", "distances"],
    )

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    hits: list[dict] = []
    for content, metadata, distance in zip(documents, metadatas, distances):
        meta = metadata or {}
        hits.append({
            "path": meta.get("source", "inconnu"),
            "content": content,
            "score": round(1.0 - float(distance), 4),  # distance cosinus -> similarite
            "symbol": meta.get("symbol", "<file>"),
            "kind": meta.get("kind", "block"),
            "start_line": meta.get("start_line", 1),
            "end_line": meta.get("end_line", 1),
        })
    return hits


def search_many(
    repo_keys: Iterable[str],
    query: str,
    top_k: int = RAG_TOP_K,
) -> list[dict]:
    """
    Recherche vectorielle sur plusieurs depots et fusionne les resultats
    par score decroissant. Chaque hit porte une cle 'repo_key'.
    """
    merged: list[dict] = []
    for repo_key in repo_keys:
        for hit in similarity_search(repo_key, query, top_k=top_k):
            hit["repo_key"] = repo_key
            merged.append(hit)
    merged.sort(key=lambda h: h["score"], reverse=True)
    return merged[:top_k]


def delete_repo_index(repo_key: str) -> bool:
    """Supprime l'index vectoriel d'un depot. Retourne True si supprime."""
    with _index_lock:
        try:
            _get_client().delete_collection(_collection_name(repo_key))
            return True
        except Exception:
            return False
