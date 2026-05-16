"""
main.py  —  PM-B IA Service
============================
Service FastAPI pour l'analyse de dépôts GitHub et la génération d'entités.

Architecture de sécurité des PAT GitHub :
  1. Le frontend envoie le PAT en clair via HTTPS lors de l'ajout d'un dépôt privé.
  2. Le service IA chiffre immédiatement le token avec Fernet (ENCRYPTION_KEY du .env).
  3. Seule la version chiffrée est envoyée au backend Java (PM-B-backend) pour persistance
     via POST /api/repos/upsert — la base de données PostgreSQL ne stocke jamais de token clair.
  4. À chaque appel d'analyse, le token chiffré est récupéré depuis le backend Java,
     puis déchiffré en RAM — il ne transite jamais en clair entre services.

Nettoyage :
  - Toute logique "GitHub App" (OAuth, client_id, client_secret) a été supprimée.
  - Le fichier database_service.py (SQLite local) a été supprimé — la persistance
    se fait désormais via le backend Java Spring Boot (PostgreSQL).
"""

import os
# ─── Résolution du conflit OpenMP (Anaconda Windows) ──────────────────────────
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import asyncio
import json
import requests as req
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import uvicorn
import os
import tempfile

from config.config import LLM_MODEL, BACKEND_BASE_URL
from services.github_service import fetch_file_tree, fetch_file_content
from services.rag_service import identify_relevant_files, answer_repo_question, generate_entity, generate_ask_ai_content
from services.encryption_service import encrypt_token, decrypt_token
from services.transcription_service import transcribe_audio

# ─── Initialisation de l'application ────────────────────────────────────────

app = FastAPI(
    title="PM-B IA API",
    description="Service d'intelligence artificielle pour l'analyse de dépôts GitHub et la gestion de projet.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_errors(request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        import traceback
        print(f"CRITICAL ERROR on {request.url.path}: {str(e)}")
        traceback.print_exc()
        raise e


# ─── Modèles Pydantic ────────────────────────────────────────────────────────

class RepoInfo(BaseModel):
    """
    Informations d'un dépôt GitHub transmises par le frontend.

    Attributs:
        owner:        Login GitHub du propriétaire.
        repo:         Nom du dépôt.
        branch:       Branche à analyser (défaut : "main").
        is_private:   True si le dépôt est privé — déclenche l'utilisation du PAT.
        github_token: PAT GitHub en clair, transmis uniquement à l'ajout/validation.
                      N'est JAMAIS stocké en clair ni renvoyé au client.
    """
    owner:        str
    repo:         str
    branch:       str       = "main"
    is_private:   bool      = False
    github_token: Optional[str] = Field(default=None, exclude=True)


class RepoAnalysisRequest(BaseModel):
    repositories: list[RepoInfo]
    user_query:   str
    user_id:      str = "anonymous"


class GenerateRequest(BaseModel):
    user_query:   str
    context:      Optional[dict]           = None
    repositories: Optional[list[RepoInfo]] = None
    user_id:      str = "anonymous"


class AddRepoRequest(BaseModel):
    """Corps de la requête POST /api/ia/repos/add."""
    owner:        str
    repo:         str
    branch:       str  = "main"
    is_private:   bool = False
    github_token: Optional[str] = Field(default=None, exclude=True)
    user_id:      str  = "anonymous"


class DeleteRepoRequest(BaseModel):
    owner:   str
    repo:    str
    user_id: str = "anonymous"


class AskAIRequest(BaseModel):
    entity_type: str
    entity_name: str


# ─── Clients HTTP Backend Java ───────────────────────────────────────────────

def _backend_url(path: str) -> str:
    """Construit l'URL complète vers le backend Java."""
    return f"{BACKEND_BASE_URL}{path}"


def _upsert_repo_in_backend(
    user_id: str,
    repo_owner: str,
    repo_name: str,
    branch: str,
    is_private: bool,
    github_token_encrypted: Optional[str],
) -> dict:
    """
    Appelle POST /api/repos/upsert sur le backend Java pour persister le dépôt.
    Seul le token CHIFFRÉ est transmis — jamais le token brut.
    """
    payload = {
        "userId":                user_id,
        "repoOwner":             repo_owner,
        "repoName":              repo_name,
        "branch":                branch,
        "isPrivate":             is_private,
        "githubTokenEncrypted":  github_token_encrypted,
    }
    try:
        r = req.post(_backend_url("/api/repos/upsert"), json=payload, timeout=10)
        r.raise_for_status()
        return r.json()
    except req.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Impossible de joindre le backend Java. Vérifiez que PM-B-backend est démarré sur le port 8080.",
        )
    except req.exceptions.HTTPError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Erreur backend lors de l'enregistrement du dépôt : {exc.response.text}",
        ) from exc


def _get_encrypted_token_from_backend(
    user_id: str,
    repo_owner: str,
    repo_name: str,
) -> Optional[str]:
    """
    Récupère le token chiffré depuis le backend Java.
    Retourne None si le dépôt n'a pas de token enregistré.
    """
    url = _backend_url(f"/api/repos/{user_id}/{repo_owner}/{repo_name}/token")
    try:
        r = req.get(url, timeout=8)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("encryptedToken")
    except req.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Impossible de joindre le backend Java pour récupérer le token.",
        )
    except req.exceptions.HTTPError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Erreur backend lors de la récupération du token : {exc.response.text}",
        ) from exc


def _delete_repo_from_backend(user_id: str, repo_owner: str, repo_name: str) -> bool:
    """Supprime un dépôt depuis le backend Java. Retourne False si introuvable."""
    url = _backend_url(f"/api/repos/{user_id}/{repo_owner}/{repo_name}")
    try:
        r = req.delete(url, timeout=8)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return True
    except req.exceptions.ConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Impossible de joindre le backend Java pour supprimer le dépôt.",
        )
    except req.exceptions.HTTPError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Erreur backend lors de la suppression : {exc.response.text}",
        ) from exc


# ─── Helpers internes ────────────────────────────────────────────────────────

def _resolve_token_for_repo(
    user_id: str,
    repo_owner: str,
    repo_name: str,
    is_private: bool,
) -> Optional[str]:
    """
    Pour un dépôt privé, récupère le token chiffré depuis le backend Java
    et le déchiffre en mémoire vive.

    Returns:
        Le PAT déchiffré (str) si dépôt privé et token disponible, None sinon.

    Raises:
        HTTPException 403: Si le dépôt est privé mais qu'aucun token n'est enregistré.
        HTTPException 500: Si le déchiffrement échoue (clé incorrecte/corrompue).
    """
    if not is_private:
        return None

    encrypted_token = _get_encrypted_token_from_backend(user_id, repo_owner, repo_name)

    if not encrypted_token:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Dépôt privé '{repo_owner}/{repo_name}' : aucun Personal Access Token "
                "enregistré. Veuillez re-ajouter le dépôt avec votre PAT."
            ),
        )

    try:
        return decrypt_token(encrypted_token)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Impossible de déchiffrer le token GitHub : {exc}",
        ) from exc


# ─── Endpoints — Gestion des dépôts ─────────────────────────────────────────

@app.post("/api/ia/repos/add")
async def add_repository(request: AddRepoRequest):
    """
    Ajoute ou met à jour un dépôt GitHub pour un utilisateur.

    Flux de sécurité :
      1. Validation de l'existence du dépôt via l'API GitHub.
      2. Si privé : chiffrement du PAT avec Fernet (en mémoire).
      3. Envoi du token CHIFFRÉ au backend Java (POST /api/repos/upsert) pour
         persistance en PostgreSQL — le token brut n'atteint jamais la BDD.

    Returns:
        Informations publiques du dépôt (sans token ni données sensibles).
    """
    # 1. Valider l'existence du dépôt sur GitHub
    token_for_validation = request.github_token if request.is_private else None
    gh_url = f"https://api.github.com/repos/{request.owner}/{request.repo}"
    gh_headers = {"Accept": "application/vnd.github+json"}
    if token_for_validation:
        gh_headers["Authorization"] = f"Bearer {token_for_validation}"

    try:
        r = req.get(gh_url, headers=gh_headers, timeout=8)
        if r.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Dépôt '{request.owner}/{request.repo}' introuvable ou inaccessible avec ce token.",
            )
        if r.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Token GitHub invalide ou expiré. Vérifiez votre Personal Access Token.",
            )
        if r.status_code != 200:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Erreur GitHub API : {r.status_code}",
            )
        gh_data = r.json()
        
        # 1.5. Validate branch existence or fallback to default branch
        if not request.branch:
            request.branch = gh_data.get("default_branch", "main")
        else:
            branch_url = f"https://api.github.com/repos/{request.owner}/{request.repo}/branches/{request.branch}"
            br = req.get(branch_url, headers=gh_headers, timeout=5)
            if br.status_code == 404:
                # If requested branch doesn't exist, check if default branch works instead
                default_branch = gh_data.get("default_branch", "main")
                if request.branch != default_branch:
                    request.branch = default_branch # Auto-fix to default branch
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"La branche '{request.branch}' n'existe pas dans ce dépôt.",
                    )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Impossible de contacter GitHub : {exc}") from exc

    # 2. Chiffrer le PAT si le dépôt est privé
    encrypted_token: Optional[str] = None
    if request.is_private:
        if not request.github_token:
            raise HTTPException(
                status_code=422,
                detail="Un Personal Access Token est obligatoire pour les dépôts privés.",
            )
        try:
            encrypted_token = encrypt_token(request.github_token)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Erreur de chiffrement du token : {exc}",
            ) from exc

    # 3. Persister via le backend Java (token chiffré uniquement)
    await asyncio.to_thread(
        _upsert_repo_in_backend,
        request.user_id,
        request.owner,
        request.repo,
        request.branch,
        request.is_private,
        encrypted_token,
    )

    return {
        "status":         "ok",
        "message":        f"Dépôt '{request.owner}/{request.repo}' enregistré avec succès.",
        "full_name":      gh_data.get("full_name"),
        "default_branch": gh_data.get("default_branch", "main"),
        "is_private":     gh_data.get("private", False),
        "token_stored":   request.is_private,
    }


@app.post("/api/ia/validate")
async def validate_repo(request: RepoInfo):
    """
    Vérifie si un dépôt GitHub existe et est accessible.
    Pour les dépôts privés, utilise le token fourni dans la requête.
    """
    gh_url = f"https://api.github.com/repos/{request.owner}/{request.repo}"
    gh_headers = {"Accept": "application/vnd.github+json"}
    if request.github_token:
        gh_headers["Authorization"] = f"Bearer {request.github_token}"

    try:
        r = req.get(gh_url, headers=gh_headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {
                "status":         "ok",
                "full_name":      data.get("full_name"),
                "default_branch": data.get("default_branch", "main"),
                "private":        data.get("private", False),
            }
        elif r.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Dépôt '{request.owner}/{request.repo}' introuvable ou privé sans token.",
            )
        elif r.status_code == 401:
            raise HTTPException(status_code=401, detail="Token GitHub invalide ou expiré.")
        else:
            raise HTTPException(status_code=r.status_code, detail=f"Erreur GitHub : {r.status_code}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Impossible de contacter GitHub : {exc}") from exc


@app.delete("/api/ia/repos/delete")
async def remove_repository(request: DeleteRepoRequest):
    """Supprime un dépôt (et son token chiffré) depuis le backend Java."""
    deleted = await asyncio.to_thread(
        _delete_repo_from_backend, request.user_id, request.owner, request.repo
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Dépôt introuvable.")
    return {"status": "ok", "message": f"Dépôt '{request.owner}/{request.repo}' supprimé."}


# ─── Endpoints — Analyse IA ─────────────────────────────────────────────────

async def _get_repo_context(
    repositories: list[RepoInfo],
    user_query:   str,
    user_id:      str = "anonymous",
) -> tuple[dict, list[str]]:
    """
    Construit le contexte de code pour le LLM en récupérant les fichiers
    pertinents de chaque dépôt.

    Pour les dépôts privés : récupère le token chiffré depuis le backend Java,
    puis déchiffre en mémoire vive uniquement.
    """

    async def _fetch_tree(repo_info: RepoInfo):
        token = await asyncio.to_thread(
            _resolve_token_for_repo,
            user_id, repo_info.owner, repo_info.repo, repo_info.is_private,
        )
        try:
            files = await asyncio.to_thread(
                fetch_file_tree,
                repo_info.owner, repo_info.repo, repo_info.branch, token,
            )
        except req.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"La branche '{repo_info.branch}' est introuvable pour le dépôt '{repo_info.owner}/{repo_info.repo}'. Veuillez supprimer le dépôt et le rajouter avec la bonne branche (ex: master)."
                ) from e
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Erreur d'accès au dépôt '{repo_info.owner}/{repo_info.repo}': {e.response.text}"
            ) from e

        repo_key = f"{repo_info.owner}/{repo_info.repo}"
        prefixed = [f"[{repo_key}] {f}" for f in files]
        return repo_key, repo_info, prefixed, token

    tree_results = await asyncio.gather(*[_fetch_tree(r) for r in repositories])

    all_combined_files: list[str] = []
    repo_map:  dict = {}
    token_map: dict = {}

    for repo_key, repo_info, prefixed_files, token in tree_results:
        all_combined_files.extend(prefixed_files)
        repo_map[repo_key]  = repo_info
        token_map[repo_key] = token

    relevant_prefixed_files = await asyncio.to_thread(
        identify_relevant_files, all_combined_files, user_query
    )

    async def _fetch_content(prefixed_path: str):
        if not prefixed_path.startswith("[") or "] " not in prefixed_path:
            return prefixed_path, ""
        repo_key, actual_path = prefixed_path[1:].split("] ", 1)
        repo_info = repo_map.get(repo_key)
        if not repo_info:
            return prefixed_path, ""
        token = token_map.get(repo_key)
        content = await asyncio.to_thread(
            fetch_file_content,
            actual_path, repo_info.owner, repo_info.repo, repo_info.branch, token,
        )
        return prefixed_path, content

    content_results = await asyncio.gather(*[_fetch_content(p) for p in relevant_prefixed_files])
    files_content = {path: content for path, content in content_results if content}
    return files_content, relevant_prefixed_files


@app.post("/api/ia/repo")
async def analyze_repo(request: RepoAnalysisRequest):
    """
    Analyse plusieurs dépôts GitHub et répond à la question de l'utilisateur.
    Les PAT des dépôts privés sont récupérés depuis le backend Java et
    déchiffrés en mémoire vive uniquement.
    """
    try:
        if not request.repositories:
            return {
                "response":   "Veuillez ajouter au moins un dépôt GitHub pour commencer l'analyse.",
                "files_used": [],
            }

        files_content, relevant_prefixed_files = await _get_repo_context(
            request.repositories, request.user_query, request.user_id
        )
        answer = await asyncio.to_thread(answer_repo_question, files_content, request.user_query)

        return {
            "response":   answer,
            "files_used": relevant_prefixed_files,
            "model":      LLM_MODEL,
        }

    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/ia/generate")
async def generate_from_intent(request: GenerateRequest):
    """
    Détecte l'intention de l'utilisateur et retourne un objet JSON structuré
    représentant l'entité à créer (tâche, workspace, sprint, etc.).
    """
    try:
        repo_context_str = ""
        if request.repositories:
            files_content, _ = await _get_repo_context(
                request.repositories, request.user_query, request.user_id
            )
            if files_content:
                repo_context_str = "\n".join(
                    [f"--- Fichier: {path} ---\n{content}\n" for path, content in files_content.items()]
                )

        result = await asyncio.to_thread(
            generate_entity, request.user_query, request.context or {}, repo_context_str
        )
        return result

    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/ia/ask-ai")
async def ask_ai_generation(request: AskAIRequest):
    """
    Endpoint spécialisé pour la génération de contenu (description/objectif)
    basé sur le nom d'une entité et son type.
    """
    try:
        result = await asyncio.to_thread(
            generate_ask_ai_content, request.entity_type, request.entity_name
        )
        return result
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/ia/transcribe")
async def transcribe_audio_endpoint(
    audio_file: UploadFile = File(...),
    language: str = Form("fr")
):
    """
    Endpoint pour la transcription audio via API (Gemini/Whisper via OpenRouter).
    Remplace la transcription locale pour plus de précision et moins de charge client.
    """
    try:
        content = await audio_file.read()
        transcription = await transcribe_audio(content, audio_file.filename, language)
        return {"text": transcription}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erreur transcription API : {str(exc)}")


# ─── Démarrage ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
