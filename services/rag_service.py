from functools import lru_cache
import json
import re
import time
import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config.config import OPENAI_API_KEY, OPENAI_API_BASE, LLM_MODEL

# -----------------------------------------------------------------
# Singleton ChatOpenAI
# -----------------------------------------------------------------
@lru_cache(maxsize=1)
def _get_chat() -> ChatOpenAI:
    return ChatOpenAI(
        model_name=LLM_MODEL,
        openai_api_key=OPENAI_API_KEY,
        openai_api_base=OPENAI_API_BASE,
    )


def identify_relevant_files(files_tree: list, user_query: str) -> list:
    """LLM 1 : Identifie les fichiers les plus pertinents."""
    chat = _get_chat()
    tree_str = "\n".join(files_tree)

    prompt = (
        f"Arborescence de depots GitHub :\n{tree_str}\n\n"
        f"Question : \"{user_query}\"\n\n"
        "Retourne UNIQUEMENT les 3 a 5 chemins de fichiers (tels qu'ils apparaissent "
        "dans la liste ci-dessus) les plus utiles pour repondre a cette question, "
        "un par ligne, sans texte supplementaire."
    )

    response = chat.invoke([HumanMessage(content=prompt)])
    paths = [p.strip() for p in response.content.split("\n") if p.strip()]
    return [p for p in paths if p in files_tree][:5]


def answer_repo_question(files_content: dict, user_query: str) -> str:
    chat = _get_chat()

    context = ""
    for path, content in files_content.items():
        context += f"\n--- {path} ---\n{content[:1500]}\n"

    prompt = (
        f"Tu es un Tech Lead expert. Voici des extraits de code :\n{context}\n"
        f"Question : \"{user_query}\"\n\n"
        "Reponds de facon precise et technique en Francais. "
        "N'entre pas dans les details sauf si explicitement demande."
    )

    response = chat.invoke([HumanMessage(content=prompt)])
    return response.content


# -----------------------------------------------------------------
# Schemas des entites du backend Spring Boot
# -----------------------------------------------------------------
ENTITY_SCHEMAS = {
    "task": {
        "endpoint": "POST /api/tasks",
        "fields": {
            "title": "string (requis) - titre de la tache",
            "description": "string - description detaillee",
            "status": "enum: TO_DO | IN_DEV | IN_TEST | IN_REVIEW | DONE",
            "priority": "enum: LOW | MEDIUM | HIGH | URGENT",
            "dueDate": "string ISO 8601 (ex: 2026-06-01T09:00:00) - date d'echeance",
            "listeId": "string UUID - ID de la liste parente (si connu)",
            "sprintId": "string UUID - ID du sprint (si connu)",
            "assigneeId": "string UUID - ID du membre assigne (si connu)",
        }
    },
    "workspace": {
        "endpoint": "POST /api/workspaces",
        "fields": {
            "name": "string (requis) - nom du workspace",
            "slug": "string (requis) - identifiant URL (ex: mon-workspace)",
        }
    },
    "space": {
        "endpoint": "POST /api/spaces",
        "fields": {
            "name": "string (requis) - nom du space",
            "workspaceId": "string UUID (requis) - ID du workspace parent",
        }
    },
    "sprint": {
        "endpoint": "POST /api/sprints",
        "fields": {
            "name": "string (requis) - nom du sprint",
            "startDate": "string ISO 8601 - date de debut",
            "endDate": "string ISO 8601 - date de fin",
            "spaceId": "string UUID - ID du space parent",
        }
    },
    "folder": {
        "endpoint": "POST /api/folders",
        "fields": {
            "name": "string (requis) - nom du dossier",
            "description": "string - description du dossier",
            "spaceId": "string UUID (requis) - ID du space parent",
        }
    },
    "liste": {
        "endpoint": "POST /api/listes",
        "fields": {
            "name": "string (requis) - nom de la liste",
            "type": "enum: SPRINT | PHASE",
            "order": "number - ordre d'affichage",
            "folderId": "string UUID - ID du dossier parent",
            "sprintId": "string UUID - ID du sprint parent (si pertinent)",
        }
    },
}

INTENT_KEYWORDS = {
    "task": ["tache", "task", "todo", "ticket", "issue", "fiche"],
    "workspace": ["workspace", "espace de travail", "projet global"],
    "space": ["space", "espace", "section"],
    "folder": ["folder", "dossier", "repertoire"],
    "sprint": ["sprint", "iteration"],
    "liste": ["liste", "list", "colonne", "column"],
}


_swagger_cache = {"time": 0, "data": ""}

def fetch_openapi_schemas() -> str:
    global _swagger_cache
    if time.time() - _swagger_cache["time"] < 300 and _swagger_cache["data"]:
        return _swagger_cache["data"]
        
    try:
        resp = httpx.get("http://localhost:8080/v3/api-docs", timeout=3.0)
        if resp.status_code == 200:
            openapi = resp.json()
            paths = openapi.get("paths", {})
            schemas_info = []
            for path, methods in paths.items():
                if "post" in methods:
                    post_info = methods["post"]
                    tags = post_info.get("tags", ["unknown"])
                    summary = post_info.get("summary", "")
                    req_body = post_info.get("requestBody", {})
                    
                    schema_ref = ""
                    try:
                        content = req_body.get("content", {})
                        if "application/json" in content:
                            schema_ref = content["application/json"]["schema"]["$ref"]
                    except Exception:
                        pass
                    
                    schema_desc = ""
                    if schema_ref:
                        schema_name = schema_ref.split("/")[-1]
                        schema_obj = openapi.get("components", {}).get("schemas", {}).get(schema_name, {})
                        props = schema_obj.get("properties", {})
                        schema_desc = ", ".join([f"{k} ({v.get('type', 'any')})" for k, v in props.items()])

                    schemas_info.append(f"Endpoint: POST {path}\nRole: {summary} (Tags: {', '.join(tags)})\nFields: {schema_desc}")
            
            result = "\n\n".join(schemas_info)
            if result:
                _swagger_cache["data"] = result
                _swagger_cache["time"] = time.time()
                return result
    except Exception as e:
        print(f"Failed to fetch swagger: {e}")
    return ""


def generate_entity(user_query: str, context: dict, repo_context: str = "") -> dict:
    """
    Detecte l'intention de creation et genere les donnees JSON de l'entite.
    Retourne:
      {
        "intent": "task" | "workspace" | "space" | "sprint" | "liste" | "unknown",
        "entity": { ... champs a envoyer au backend ... },
        "endpoint": "POST /api/tasks",
        "explanation": "message pour l'utilisateur"
      }
    """
    chat = _get_chat()
    
    swagger_docs = fetch_openapi_schemas()
    if swagger_docs:
        context_str = json.dumps(context, ensure_ascii=False) if context else "Aucun contexte fourni."
        repo_instruction = ""
        if repo_context:
            repo_instruction = f"\nContexte du code (dépôt GitHub) :\n{repo_context}\nUtilise ce contexte pour extraire des détails pertinents.\n"

        prompt = (
            f"Tu es un assistant IA dynamique. Voici la documentation Swagger (OpenAPI) du backend Spring Boot contenant les endpoints POST disponibles :\n"
            f"{swagger_docs}\n\n"
            f"Demande de l'utilisateur : \"{user_query}\"\n\n"
            f"Contexte disponible (IDs deja connus) :\n{context_str}\n\n"
            f"{repo_instruction}\n"
            "INSTRUCTIONS :\n"
            "1. Analyse la demande. Si l'utilisateur demande à créer une entité, trouve l'endpoint POST approprié dans la documentation Swagger.\n"
            "2. Détermine l'intention ('intent') parmi : task, workspace, space, sprint, liste, folder.\n"
            "3. Si l'utilisateur demande ce qu'il peut générer, ou si la demande n'est pas claire, mets 'intent' à 'unknown'.\n"
            "4. Génère un JSON valide avec exactement ces clés :\n"
            "   - 'intent': Le nom de l'entité (ou 'unknown').\n"
            "   - 'endpoint': L'endpoint exact trouvé (ex: POST /api/tasks) (ou null si unknown).\n"
            "   - 'entity': L'objet JSON correspondant aux champs requis par l'API (ou null si unknown). Si l'utilisateur demande plusieurs entités du meme type, retourne un tableau d'objets (max 5).\n"
            "   - 'explanation': Un message clair en Markdown. Si tu as généré une entité, confirme l'action en précisant quel endpoint sera appelé. Si 'intent' est 'unknown', ce message DOIT lister à l'utilisateur tout ce qu'il peut générer (Space, Folder, List, Sprint, Task, Workspace) en incluant une brève description et l'endpoint Swagger associé pour chaque entité.\n"
            "5. Utilise les IDs du contexte si applicables (ex: workspaceId, spaceId, listeId, folderId, sprintId).\n"
            "6. Si un utilisateur mentionne une personne (ex: 'assigne à Ilyass'), cherche son ID dans la liste 'members' fournie dans le contexte et utilise-le pour 'assigneeId'.\n"
            "7. Pour status utilise TO_DO par defaut. Pour priority utilise MEDIUM par defaut.\n"
            "8. Retourne UNIQUEMENT le JSON de la réponse, sans markdown en dehors du JSON.\n\n"
            "JSON :"
        )
        
        response = chat.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        try:
            parsed = json.loads(raw)
            entity = parsed.get("entity")
            if parsed.get("intent") != "unknown" and entity:
                explanation = parsed.get("explanation") or f"L'IA a généré dynamiquement via Swagger un(e) {parsed.get('intent')}."
                if isinstance(entity, list):
                    entity_items = [item for item in entity if isinstance(item, dict)]
                    if not entity_items:
                        return {
                            "intent": "unknown",
                            "entity": None,
                            "endpoint": None,
                            "explanation": "Je n'ai pas pu interpreter correctement les entites demandees. Merci de reformuler."
                        }
                    limited = False
                    if len(entity_items) > 5:
                        entity_items = entity_items[:5]
                        limited = True
                    for item in entity_items:
                        for ctx_key in ["listeId", "spaceId", "workspaceId", "sprintId", "folderId"]:
                            if ctx_key in context and ctx_key not in item:
                                item[ctx_key] = context[ctx_key]
                    if limited:
                        explanation = f"{explanation} (limite a 5 elements)"
                    return {
                        "intent": parsed.get("intent", "unknown"),
                        "entity": entity_items,
                        "endpoint": parsed.get("endpoint"),
                        "explanation": explanation
                    }
                if isinstance(entity, dict):
                    for ctx_key in ["listeId", "spaceId", "workspaceId", "sprintId", "folderId"]:
                        if ctx_key in context and ctx_key not in entity:
                            entity[ctx_key] = context[ctx_key]
                    return {
                        "intent": parsed.get("intent", "unknown"),
                        "entity": entity,
                        "endpoint": parsed.get("endpoint"),
                        "explanation": explanation
                    }
                return {
                    "intent": "unknown",
                    "entity": None,
                    "endpoint": None,
                    "explanation": "Je n'ai pas pu interpreter correctement l'entite demandee. Merci de reformuler."
                }
        except json.JSONDecodeError as e:
            print("Failed to parse dynamic swagger generation:", e)

    # === FALLBACK STATIQUE ===
    query_lower = user_query.lower()
    detected_type = "unknown"
    for entity_type, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            detected_type = entity_type
            break

    if detected_type == "unknown":
        return {
            "intent": "unknown",
            "entity": None,
            "endpoint": None,
            "explanation": "Je n'ai pas compris quelle entite creer. Essaie : 'genere une tache X', 'cree un workspace Y', etc."
        }

    schema = ENTITY_SCHEMAS[detected_type]
    context_str = json.dumps(context, ensure_ascii=False) if context else "Aucun contexte fourni."
    fields_desc = "\n".join([f"  - {k}: {v}" for k, v in schema["fields"].items()])

    repo_instruction = ""
    if repo_context:
        repo_instruction = f"\nContexte du code (dépôt GitHub) :\n{repo_context}\nUtilise ce contexte de code pour générer des informations pertinentes si nécessaire (par exemple, des tâches de dev, des descriptions techniques).\n"

    prompt = (
        f"Tu es un assistant de gestion de projet. L'utilisateur veut creer un(e) {detected_type}.\n\n"
        f"Demande de l'utilisateur : \"{user_query}\"\n\n"
        f"Contexte disponible (IDs deja connus) :\n{context_str}\n\n"
        f"Champs disponibles pour {detected_type} :\n{fields_desc}\n{repo_instruction}\n"
        "INSTRUCTIONS :\n"
        "1. Genere UNIQUEMENT un objet JSON valide avec les champs pertinents.\n"
        "2. Utilise les IDs du contexte si disponibles (ex: listeId, spaceId, workspaceId).\n"
        "3. Pour les champs optionnels non mentionnes, omets-les.\n"
        "4. Pour status utilise TO_DO par defaut. Pour priority utilise MEDIUM par defaut.\n"
        "5. Retourne SEULEMENT le JSON, sans markdown, sans explication.\n\n"
        "JSON :"
    )

    response = chat.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    # Nettoyer si l'IA a ajoute des backticks markdown
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    try:
        entity_data = json.loads(raw)
    except json.JSONDecodeError:
        entity_data = {"title": user_query, "status": "TO_DO", "priority": "MEDIUM"}

    # Injecter le contexte si champs manquants
    for ctx_key in ["listeId", "spaceId", "workspaceId", "sprintId"]:
        if ctx_key in context and ctx_key not in entity_data:
            entity_data[ctx_key] = context[ctx_key]

    return {
        "intent": detected_type,
        "entity": entity_data,
        "endpoint": schema["endpoint"],
        "explanation": f"L'IA a genere un(e) {detected_type} base sur votre demande. Verifiez les details ci-dessous avant de confirmer."
    }
