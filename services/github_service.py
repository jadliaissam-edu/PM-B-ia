"""
github_service.py
-----------------
Service d'accès à l'API GitHub REST.

Fonctionnalités :
  - fetch_file_tree()   : récupère la liste des fichiers d'un dépôt.
  - fetch_file_content(): télécharge le contenu brut d'un fichier.
  - get_latest_commit() : retourne le SHA du dernier commit.

Sécurité des tokens :
  - Les fonctions acceptent un paramètre optionnel `github_token` (str).
  - Si fourni, ce token (déjà déchiffré en mémoire par main.py)
    est utilisé dans le header Authorization.
  - Aucun token n'est jamais persisté dans ce fichier.

Cache mémoire :
  - Arbre de fichiers : TTL 5 min (le dépôt change peu souvent).
  - Contenu de fichier : TTL 10 min (stabilité entre les requêtes).
  - Thread-safe via threading.Lock().
"""

import threading
import time
import requests
from config.config import ALLOWED_EXTENSIONS


# ─── Cache mémoire TTL ──────────────────────────────────────────────────────

_tree_cache:    dict = {}   # { cache_key: (timestamp, data) }
_content_cache: dict = {}   # { cache_key: (timestamp, data) }
_cache_lock = threading.Lock()

_TREE_TTL    = 300    # secondes (5 min)
_CONTENT_TTL = 600    # secondes (10 min)


def _cache_get(store: dict, key: str, ttl: int):
    """Retourne la valeur en cache si encore valide, sinon None."""
    with _cache_lock:
        entry = store.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
    return None


def _cache_set(store: dict, key: str, value) -> None:
    with _cache_lock:
        store[key] = (time.time(), value)


# ─── Construction des headers GitHub ────────────────────────────────────────

def _gh_headers(github_token: str | None = None) -> dict:
    """
    Construit les headers HTTP pour l'API GitHub.

    Args:
        github_token: PAT GitHub déchiffré en mémoire (optionnel).
                      Requis pour les dépôts privés.

    Returns:
        Dict de headers HTTP prêts à être utilisés avec requests.
    """
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers


# ─── Fonctions publiques ─────────────────────────────────────────────────────

def fetch_file_tree(
    owner:        str,
    repo:         str,
    branch:       str        = "main",
    github_token: str | None = None,
) -> list[str]:
    """
    Récupère la liste de tous les fichiers du dépôt (extensions autorisées).
    Résultat mis en cache 5 minutes pour limiter les appels à l'API GitHub.

    Args:
        owner:        Login du propriétaire GitHub.
        repo:         Nom du dépôt.
        branch:       Branche cible (défaut : "main").
        github_token: PAT déchiffré en mémoire (requis pour dépôts privés).

    Returns:
        Liste des chemins de fichiers filtrés par extension.

    Raises:
        requests.HTTPError: Si l'API GitHub retourne une erreur (401, 404…).
    """
    cache_key = f"{owner}/{repo}@{branch}"
    cached = _cache_get(_tree_cache, cache_key, _TREE_TTL)
    if cached is not None:
        return cached

    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    r = requests.get(url, headers=_gh_headers(github_token), timeout=15)
    r.raise_for_status()

    tree = r.json().get("tree", [])
    result = [
        item["path"]
        for item in tree
        if item["type"] == "blob" and item["path"].endswith(ALLOWED_EXTENSIONS)
    ]

    _cache_set(_tree_cache, cache_key, result)
    return result


def fetch_file_content(
    file_path:    str,
    owner:        str,
    repo:         str,
    branch:       str        = "main",
    github_token: str | None = None,
) -> str:
    """
    Télécharge le contenu brut d'un fichier depuis GitHub.
    Résultat mis en cache 10 minutes.

    Args:
        file_path:    Chemin relatif du fichier dans le dépôt.
        owner:        Login du propriétaire GitHub.
        repo:         Nom du dépôt.
        branch:       Branche cible.
        github_token: PAT déchiffré en mémoire (requis pour dépôts privés).

    Returns:
        Contenu texte du fichier, ou chaîne vide en cas d'erreur.
    """
    cache_key = f"{owner}/{repo}@{branch}:{file_path}"
    cached = _cache_get(_content_cache, cache_key, _CONTENT_TTL)
    if cached is not None:
        return cached

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
    headers = _gh_headers(github_token)
    headers["Accept"] = "application/vnd.github.v3.raw"

    r = requests.get(url, headers=headers, timeout=15)

    if r.status_code == 200:
        _cache_set(_content_cache, cache_key, r.text)
        return r.text
    else:
        print(f"[github_service] Erreur {r.status_code} pour {file_path}: {r.text[:200]}")
        return ""


def get_latest_commit(
    owner:        str,
    repo:         str,
    branch:       str        = "main",
    github_token: str | None = None,
) -> str:
    """
    Retourne le SHA du dernier commit sur la branche donnée.

    Args:
        owner:        Login du propriétaire GitHub.
        repo:         Nom du dépôt.
        branch:       Branche cible.
        github_token: PAT déchiffré en mémoire (requis pour dépôts privés).

    Returns:
        SHA du dernier commit (str).

    Raises:
        requests.HTTPError: Si l'API GitHub retourne une erreur.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    r = requests.get(url, headers=_gh_headers(github_token), timeout=10)
    r.raise_for_status()
    return r.json()["sha"]
