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

class RepoAnalysisRequest(BaseModel):
    owner: str
    repo: str
    branch: str = "main"
    user_query: str

# --- Endpoints ---

@app.post("/api/ia/repo")
def analyze_repo(request: RepoAnalysisRequest):
    """
    Endpoint qui délègue toute la logique au rag_service.
    """
    try:
        # 1. Récupération de l'arbre (via github_service)
        all_files = fetch_file_tree(request.owner, request.repo, request.branch)
        
        # 2. Identification des fichiers (via rag_service)
        relevant_files = identify_relevant_files(all_files, request.user_query)
        
        # 3. Récupération du contenu
        files_content = {}
        for path in relevant_files:
            # Utilise des arguments nommés pour éviter les erreurs d'ordre
            content = fetch_file_content(
                file_path=path, 
                owner=request.owner, 
                repo=request.repo, 
                branch=request.branch
            )
            if content:
                files_content[path] = content


        # 4. Analyse et réponse (via rag_service)
        answer = answer_repo_question(files_content, request.user_query)

        return {
            "response": answer,
            "files_used": relevant_files,
            "model": LLM_MODEL
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
