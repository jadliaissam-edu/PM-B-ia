import requests
from config.config import ALLOWED_EXTENSIONS

<<<<<<< Updated upstream
def _gh_headers() -> dict:
=======
# -----------------------------------------------------------------
# Optimisation : Cache TTL en mémoire (sans dépendance externe)
# - file_tree  : TTL 5 min  (le repo ne change pas souvent)
# - file_content: TTL 10 min (contenu stable entre les requêtes)
# Thread-safe grâce au verrou.
# -----------------------------------------------------------------
_tree_cache: dict = {}    # { cache_key: (timestamp, data) }
_content_cache: dict = {} # { cache_key: (timestamp, data) }
_cache_lock = threading.Lock()

_TREE_TTL    = 300   # secondes
_CONTENT_TTL = 600   # secondes


def _cache_get(store: dict, key: str, ttl: int):
    """Retourne la valeur en cache si elle est encore valide, sinon None."""
    with _cache_lock:
        entry = store.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
    return None


def _cache_set(store: dict, key: str, value):
    with _cache_lock:
        store[key] = (time.time(), value)


def _gh_headers(token: str = None) -> dict:
>>>>>>> Stashed changes
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


<<<<<<< Updated upstream
def fetch_file_tree(owner: str = None, repo: str = None, branch: str = None) -> list[str]:
    """Récupère la liste de tous les fichiers du dépôt (extensions autorisées seulement)."""
    owner  = owner  or OWNER
    repo   = repo   or REPO
    branch = branch or BRANCH
=======
def fetch_file_tree(owner: str, repo: str, branch: str, token: str = None) -> list[str]:
    """Récupère la liste de tous les fichiers du dépôt (extensions autorisées seulement).
    Résultat mis en cache 5 minutes pour éviter les appels répétés à la même API."""
>>>>>>> Stashed changes

    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, headers=headers)
    r.raise_for_status()

    tree = r.json().get("tree", [])
    return [
        item["path"]
        for item in tree
        if item["type"] == "blob" and item["path"].endswith(ALLOWED_EXTENSIONS)
    ]


import requests

<<<<<<< Updated upstream
def fetch_file_content(file_path: str, owner: str = None, repo: str = None, branch: str = None) -> str:
    """Télécharge le contenu brut d'un fichier depuis GitHub."""
    
    owner = owner or OWNER
    repo = repo or REPO
    branch = branch or BRANCH
=======
def fetch_file_content(file_path: str, owner: str, repo: str, branch: str, token: str = None) -> str:
    """Télécharge le contenu brut d'un fichier depuis GitHub.
    Résultat mis en cache 10 minutes."""
>>>>>>> Stashed changes

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
<<<<<<< Updated upstream
    
    headers = _gh_headers()
    headers["Accept"] = "application/vnd.github.v3.raw"
=======
    headers = {"Accept": "application/vnd.github.v3.raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
>>>>>>> Stashed changes

    r = requests.get(url, headers=headers)

    if r.status_code == 200:
        return r.text
    else:
        print(f"Erreur {r.status_code}: {r.text}")
        return ""


def get_latest_commit(owner: str, repo: str, branch: str, token: str = None) -> str:
    """Retourne le SHA du dernier commit."""

    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    r = requests.get(url, headers=_gh_headers(token))
    r.raise_for_status()
    return r.json()["sha"]
