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
    LLM 1 : Identifie les fichiers les plus pertinents dans l'arborescence 
    pour répondre à la question de l'utilisateur.
    """
    chat = _get_chat()
    tree_str = "\n".join(files_tree)
    
    prompt = f"""Tu es un expert en architecture. Voici l'arborescence d'un projet :
{tree_str}

Requête utilisateur : "{user_query}"

MANDAT :
Identifie les 3 chemins de fichiers les plus importants à lire pour répondre.
Retourne UNIQUEMENT les chemins, un par ligne, sans texte autour."""

    response = chat.invoke([HumanMessage(content=prompt)])
    paths = [p.strip() for p in response.content.split('\n') if p.strip()]
    return [p for p in paths if p in files_tree][:3]

def answer_repo_question(files_content: dict, user_query: str) -> str:
    """
    LLM 2 : Répond à une question générale en se basant sur le contenu des fichiers.
    C'est ici que l'IA "répond sur tout ce qui concerne le repo".
    """
    chat = _get_chat()
    
    context = ""
    for path, content in files_content.items():
        context += f"\n--- FICHIER : {path} ---\n{content[:3000]}\n"

    prompt = f"""Tu es un Tech Lead expert. Tu dois aider un développeur sur son projet.

CONTEXTE DU CODE :
{context}

DEMANDE : "{user_query}"

MISSION :
Réponds de manière précise et technique. Si l'utilisateur demande des tickets, génère-les. 
S'il demande une explication, explique. S'il demande de corriger un bug, propose le code.
Ne reponds pas sur des chose qui ne concerne pas le projet.
Réponds toujours en Français."""

    response = chat.invoke([HumanMessage(content=prompt)])
    return response.content
