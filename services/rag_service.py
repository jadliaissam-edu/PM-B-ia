import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config.config import OPENAI_API_KEY, OPENAI_API_BASE, LLM_MODEL

def _get_chat():
    return ChatOpenAI(
        model_name=LLM_MODEL,
        openai_api_key=OPENAI_API_KEY,
        openai_api_base=OPENAI_API_BASE
    )

def identify_relevant_files(files_tree: list, user_query: str) -> list:
    """
    LLM 1 : Identifie les fichiers les plus pertinents à travers plusieurs dépôts.
    Les chemins sont au format "[owner/repo] path/to/file".
    """
    chat = _get_chat()
    tree_str = "\n".join(files_tree)
    
    prompt = f"""Tu es un expert en architecture logicielle. Voici l'arborescence combinée de plusieurs dépôts GitHub :
{tree_str}

Requête utilisateur : "{user_query}"

MANDAT :
Identifie les 3 à 5 fichiers les plus importants (parmi tous les dépôts) à lire pour répondre à cette demande.
Note : Les chemins commencent par "[owner/repo]". Retourne UNIQUEMENT les chemins exacts tels qu'ils apparaissent dans la liste, un par ligne, sans texte autour."""

    response = chat.invoke([HumanMessage(content=prompt)])
    paths = [p.strip() for p in response.content.split('\n') if p.strip()]
    return [p for p in paths if p in files_tree][:5]

def answer_repo_question(files_content: dict, user_query: str) -> str:
    """
    LLM 2 : Répond à une question en se basant sur le contenu de fichiers de plusieurs repos.
    """
    chat = _get_chat()
    
    context = ""
    for path, content in files_content.items():
        context += f"\n--- REPO/FICHIER : {path} ---\n{content[:3000]}\n"

    prompt = f"""Tu es un Tech Lead expert multi-projets. Tu dois aider un développeur sur son écosystème de dépôts.

CONTEXTE DU CODE (Provenant de différents dépôts) :
{context}

DEMANDE : "{user_query}"

MISSION :
Réponds de manière précise et technique. Si la demande concerne l'interaction entre les dépôts, explique-la,n'entres pas dans les details seulement lorsqu'on te le demande explicitement. 
Réponds toujours en Français."""

    response = chat.invoke([HumanMessage(content=prompt)])
    return response.content
