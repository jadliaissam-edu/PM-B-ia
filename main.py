from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

# On importe les services
from config.config import LLM_MODEL
from services.github_service import fetch_file_tree, fetch_file_content
from services.rag_service import identify_relevant_files, answer_repo_question

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

# --- Endpoints ---

@app.post("/api/ia/repo")
def analyze_repo(request: RepoAnalysisRequest):
    """
    Endpoint qui analyse plusieurs dépôts et répond à la question de l'utilisateur.
    """
    try:
        all_combined_files = []
        repo_map = {} # Pour garder trace de quel fichier appartient à quel repo si besoin

        # 1. Récupération des arbres de tous les dépôts
        if not request.repositories:
            return {"response": "Veuillez ajouter au moins un dépôt GitHub pour commencer l'analyse.", "files_used": []}

        for repo_info in request.repositories:
            # On utilise une clé unique pour le map au cas où (owner/repo)
            repo_key = f"{repo_info.owner}/{repo_info.repo}"
            files = fetch_file_tree(repo_info.owner, repo_info.repo, repo_info.branch)
            
            # On préfixe par la clé pour que l'identification soit sans ambiguïté
            prefixed_files = [f"[{repo_key}] {f}" for f in files]
            all_combined_files.extend(prefixed_files)
            repo_map[repo_key] = repo_info

        # 2. Identification des fichiers pertinents globalement
        relevant_prefixed_files = identify_relevant_files(all_combined_files, request.user_query)
        
        # 3. Récupération du contenu
        files_content = {}
        for prefixed_path in relevant_prefixed_files:
            # Format attendu: "[owner/repo] path/to/file"
            if not prefixed_path.startswith("[") or "] " not in prefixed_path:
                continue
                
            repo_key, actual_path = prefixed_path[1:].split("] ", 1)
            
            repo_info = repo_map.get(repo_key)
            if not repo_info: continue

            content = fetch_file_content(
                file_path=actual_path, 
                owner=repo_info.owner, 
                repo=repo_info.repo, 
                branch=repo_info.branch
            )
            if content:
                files_content[prefixed_path] = content

        # 4. Analyse et réponse
        answer = answer_repo_question(files_content, request.user_query)

        return {
            "response": answer,
            "files_used": relevant_prefixed_files,
            "model": LLM_MODEL
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
