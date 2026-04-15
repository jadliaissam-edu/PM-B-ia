import requests
from config.config import GITHUB_TOKEN, OWNER, REPO, BRANCH, ALLOWED_EXTENSIONS

def _gh_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def fetch_file_tree(owner: str = None, repo: str = None, branch: str = None) -> list[str]:
    """Récupère la liste de tous les fichiers du dépôt (extensions autorisées seulement)."""
    owner  = owner  or OWNER
    repo   = repo   or REPO
    branch = branch or BRANCH

    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    r = requests.get(url, headers=_gh_headers())
    r.raise_for_status()

    tree = r.json().get("tree", [])
    return [
        item["path"]
        for item in tree
        if item["type"] == "blob" and item["path"].endswith(ALLOWED_EXTENSIONS)
    ]


import requests

def fetch_file_content(file_path: str, owner: str = None, repo: str = None, branch: str = None) -> str:
    """Télécharge le contenu brut d'un fichier depuis GitHub."""
    
    owner = owner or OWNER
    repo = repo or REPO
    branch = branch or BRANCH

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}?ref={branch}"
    
    headers = _gh_headers()
    headers["Accept"] = "application/vnd.github.v3.raw"

    r = requests.get(url, headers=headers)

    if r.status_code == 200:
        return r.text
    else:
        print(f"Erreur {r.status_code}: {r.text}")
        return ""


def get_latest_commit(owner: str = None, repo: str = None, branch: str = None) -> str:
    """Retourne le SHA du dernier commit."""
    owner  = owner  or OWNER
    repo   = repo   or REPO
    branch = branch or BRANCH

    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    r = requests.get(url, headers=_gh_headers())
    r.raise_for_status()
    return r.json()["sha"]
