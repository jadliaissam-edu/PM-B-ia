import asyncio
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

from config.config import LLM_MODEL
from services.github_service import fetch_file_tree, fetch_file_content
from services.rag_service import identify_relevant_files, answer_repo_question, generate_entity

app = FastAPI(title="PM-B IA API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Modèles ---

class ChatRequest(BaseModel):
    message: str

class RepoInfo(BaseModel):
    owner: str
    repo: str
    branch: str = "main"

class RepoAnalysisRequest(BaseModel):
    repositories: list[RepoInfo]
    user_query: str

class GenerateRequest(BaseModel):
    user_query: str
    context: Optional[dict] = None   # workspaceId, spaceId, listeId, sprintId si dispo
    repositories: Optional[list[RepoInfo]] = None

# --- Endpoints ---

@app.post("/api/ia/validate")
async def validate_repo(request: RepoInfo):
    """
    Vérifie si un dépôt GitHub existe et est accessible.
    Fonctionne pour les repos publics sans token.
    """
    import requests as req
    url = f"https://api.github.com/repos/{request.owner}/{request.repo}"
    headers = {"Accept": "application/vnd.github+json"}

    # Utiliser le token si disponible (évite le rate limit)
    from config.config import GITHUB_TOKEN
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        r = req.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {
                "status": "ok",
                "full_name": data.get("full_name"),
                "default_branch": data.get("default_branch", "main"),
                "private": data.get("private", False),
            }
        elif r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Dépôt '{request.owner}/{request.repo}' introuvable ou privé.")
        else:
            raise HTTPException(status_code=r.status_code, detail=f"Erreur GitHub : {r.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de contacter GitHub : {str(e)}")

@app.post("/api/ia/generate")
async def generate_from_intent(request: GenerateRequest):
    """
    Détecte l'intention de l'utilisateur (créer task/workspace/space/sprint/liste)
    et retourne un objet JSON structuré prêt à être confirmé par l'utilisateur
    avant d'être envoyé au backend Spring Boot.
    """
    try:
        repo_context_str = ""
        if request.repositories:
            files_content, _ = await _get_repo_context(request.repositories, request.user_query)
            if files_content:
                repo_context_str = "\n".join([f"--- Fichier: {path} ---\n{content}\n" for path, content in files_content.items()])

        result = await asyncio.to_thread(
            generate_entity, request.user_query, request.context or {}, repo_context_str
        )
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def _get_repo_context(repositories: list[RepoInfo], user_query: str) -> tuple[dict, list[str]]:
    async def _fetch_tree(repo_info: RepoInfo):
        files = await asyncio.to_thread(
            fetch_file_tree, repo_info.owner, repo_info.repo, repo_info.branch
        )
        repo_key = f"{repo_info.owner}/{repo_info.repo}"
        prefixed = [f"[{repo_key}] {f}" for f in files]
        return repo_key, repo_info, prefixed

    tree_results = await asyncio.gather(*[_fetch_tree(r) for r in repositories])

    all_combined_files: list[str] = []
    repo_map: dict = {}
    for repo_key, repo_info, prefixed_files in tree_results:
        all_combined_files.extend(prefixed_files)
        repo_map[repo_key] = repo_info

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
        content = await asyncio.to_thread(
            fetch_file_content,
            actual_path,
            repo_info.owner,
            repo_info.repo,
            repo_info.branch,
        )
        return prefixed_path, content

    content_results = await asyncio.gather(*[_fetch_content(p) for p in relevant_prefixed_files])
    files_content = {path: content for path, content in content_results if content}
    return files_content, relevant_prefixed_files

@app.post("/api/ia/repo")
async def analyze_repo(request: RepoAnalysisRequest):
    """
    Endpoint qui analyse plusieurs dépôts et répond à la question de l'utilisateur.
    """
    try:
        if not request.repositories:
            return {
                "response": "Veuillez ajouter au moins un dépôt GitHub pour commencer l'analyse.",
                "files_used": [],
            }

        files_content, relevant_prefixed_files = await _get_repo_context(request.repositories, request.user_query)

        answer = await asyncio.to_thread(answer_repo_question, files_content, request.user_query)

        return {
            "response": answer,
            "files_used": relevant_prefixed_files,
            "model": LLM_MODEL,
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
