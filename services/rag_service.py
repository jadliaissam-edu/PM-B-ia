from functools import lru_cache
import json
import re
import time
import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config.config import OPENAI_API_KEY, OPENAI_API_BASE, LLM_MODEL, BACKEND_BASE_URL

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
            "description": "string - description detaillee du travail a accomplir",
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
            "description": "string - description detaillee de l'espace",
            "workspaceId": "string UUID (requis) - ID du workspace parent",
        }
    },
    "sprint": {
        "endpoint": "POST /api/sprints",
        "fields": {
            "name": "string (requis) - nom du sprint",
            "startDate": "string ISO 8601 - date de debut",
            "endDate": "string ISO 8601 - date de fin",
            "goal": "string - objectif du sprint (sprint goal)",
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
        resp = httpx.get(f"{BACKEND_BASE_URL}/v3/api-docs", timeout=10.0)
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
    Détecte les intentions de création dans l'ordre hiérarchique et génère un flux d'étapes.
    Retourne:
      {
        "flow": [
          {
            "intent": "task" | "workspace" | "space" | "sprint" | "liste" | "folder",
            "endpoint": "POST /api/...",
            "entity": { ... }
          }
        ],
        "explanation": "message pour l'utilisateur"
      }
    """
    chat = _get_chat()
    context_map = context if isinstance(context, dict) else {}

    def _inject_context(entity: dict) -> dict:
        for ctx_key in ["listeId", "spaceId", "workspaceId", "sprintId", "folderId"]:
            if ctx_key in context_map and ctx_key not in entity:
                entity[ctx_key] = context_map[ctx_key]
        return entity
    
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
            "1. Analyse la demande. Si l'utilisateur demande à créer une ou plusieurs entités (y compris une hiérarchie d'entités comme Workspace -> Space -> Folder -> List/sprint -> Task, ou plusieurs entités du même type comme 'crée 3 sprints X, Y, Z'), identifie toutes les étapes requises dans l'ordre chronologique de création.\n"
            "2. Pour chaque entité à générer, trouve l'endpoint POST approprié dans la documentation Swagger.\n"
            "3. Si la demande n'est pas claire ou si l'utilisateur ne demande pas de création, retourne un tableau 'flow' vide [].\n"
            "4. Génère un JSON valide avec exactement ces clés :\n"
            "   - 'flow': Un tableau ordonné d'objets étapes. Chaque étape doit contenir :\n"
            "       - 'intent': Le type de l'entité (parmi : task, workspace, space, sprint, liste, folder).\n"
            "       - 'endpoint': L'endpoint exact trouvé (ex: POST /api/workspaces).\n"
            "       - 'entity': L'objet JSON correspondant aux champs requis par l'API.\n"
            "   - 'explanation': Un message clair en Markdown. Confirme l'action globale d'une manière naturelle, humaine et professionnelle SANS MENTIONNER d'endpoint API, de chemin, ou de détails techniques (ne donne jamais l'URL ou le chemin API à l'utilisateur).\n"
            "5. Règle de dépendance (Marqueur) : Si une entité (ex: Space) dépend d'une entité parente (ex: Workspace) qui va être créée plus tôt dans ce même flux, utilise la valeur '__PENDING__' pour la clé de l'ID parent (ex: 'workspaceId': '__PENDING__'). Cela servira de marqueur au frontend pour pré-remplir le formulaire. Si l'ID parent est déjà dans le contexte et n'est pas créé dans ce flux, utilise l'ID du contexte.\n"
            "6. Si un utilisateur mentionne une personne (ex: 'assigne à Ilyass'), cherche son ID dans la liste 'members' fournie dans le contexte et utilise-le pour 'assigneeId'.\n"
            "7. Pour status utilise TO_DO par defaut. Pour priority utilise MEDIUM par defaut.\n"
            "8. IMPORTANT : Pour une tâche (task), un dossier (folder) ou un espace (space), génère obligatoirement une description pertinente et élaborée dans le champ 'description'. Pour un sprint, génère obligatoirement un objectif de sprint pertinent dans le champ 'goal'.\n"
            "9. INTERDICTION ABSOLUE : N'inclus JAMAIS d'explications techniques, d'exemples d'appels HTTP (ex: 'POST /api/sprints'), de corps JSON (ex: 'payload JSON'), de blocs de code ou de curl dans la clé 'explanation'. Si l'utilisateur demande de créer des sprints (ex: backend, frontend, IA), crée-les sous forme de 3 objets distincts dans le tableau 'flow'. Le champ 'explanation' doit simplement confirmer le succès de façon polie et chaleureuse (ex: 'Bien sûr ! J'ai configuré les 3 sprints demandés (backend, frontend, IA) pour vous.').\n"
            "10. Retourne UNIQUEMENT le JSON de la réponse, sans markdown en dehors du JSON.\n\n"
            "JSON :"
        )
        
        response = chat.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

        try:
            parsed = json.loads(raw)
            flow = parsed.get("flow")
            explanation = parsed.get("explanation") or "L'IA a généré un flux d'actions."
            
            if isinstance(flow, list):
                valid_flow = []
                for item in flow:
                    if not isinstance(item, dict):
                        continue
                    intent = item.get("intent", "unknown")
                    entity = item.get("entity")
                    endpoint = item.get("endpoint")
                    
                    if intent != "unknown" and isinstance(entity, dict):
                        _inject_context(entity)
                        valid_flow.append({
                            "intent": intent,
                            "endpoint": endpoint,
                            "entity": entity
                        })
                
                return {
                    "flow": valid_flow,
                    "explanation": explanation
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
            "flow": [],
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
        "5. IMPORTANT : Pour une tâche (task), un dossier (folder) ou un espace (space), génère obligatoirement une description pertinente dans le champ 'description'. Pour un sprint, génère obligatoirement un objectif de sprint pertinent dans le champ 'goal'.\n"
        "6. Retourne SEULEMENT le JSON, sans markdown, sans explication.\n\n"
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

    if isinstance(entity_data, list):
        entity_data = [item for item in entity_data if isinstance(item, dict)]
        entity_data = [_inject_context(item) for item in entity_data]
    elif isinstance(entity_data, dict):
        _inject_context(entity_data)
    else:
        entity_data = {}

    flow_steps = []
    if isinstance(entity_data, list):
        for item in entity_data:
            flow_steps.append({
                "intent": detected_type,
                "endpoint": schema["endpoint"],
                "entity": item
            })
    else:
        flow_steps.append({
            "intent": detected_type,
            "endpoint": schema["endpoint"],
            "entity": entity_data
        })

    return {
        "flow": flow_steps,
        "explanation": f"L'IA a genere un(e) {detected_type} base sur votre demande. Verifiez les details ci-dessous avant de confirmer."
    }

def generate_ask_ai_content(entity_type: str, entity_name: str) -> dict:
    """
    Génère une description ou un objectif pour une entité spécifique.
    """
    chat = _get_chat()

    prompts = {
        "space": (
            f"Tu es un Expert Agile. L'utilisateur crée un Espace nommé '{entity_name}'.\n"
            "Génère une description très brève (un seul paragraphe) de sa vision et de son utilité.\n"
            "Pas de listes, pas de tableaux, pas de code. Juste un paragraphe descriptif direct."
        ),
        "folder": (
            f"Tu es un Expert Agile. L'utilisateur crée un Dossier nommé '{entity_name}'.\n"
            "Génère une description très brève (un seul paragraphe) expliquant ce que ce dossier regroupe.\n"
            "Pas de listes, pas de tableaux, pas de code. Juste un paragraphe descriptif direct."
        ),
        "task": (
            f"Tu es un Expert Agile. L'utilisateur crée une Tâche nommée '{entity_name}'.\n"
            "Génère une description très brève (un seul paragraphe) du travail à accomplir.\n"
            "Pas de listes, pas de tableaux, pas de code. Juste un paragraphe descriptif direct."
        ),
        "sprint": (
            f"Tu es un Expert Agile. L'utilisateur crée un Sprint nommé '{entity_name}'.\n"
            "Génère un Objectif de Sprint (Sprint Goal) unique, spécifique et très bref.\n"
            "Une seule phrase percutante qui vise directement l'objectif de valeur."
        )
    }

    prompt = prompts.get(entity_type.lower())
    if not prompt:
        return {"generated_text": f"Génération pour {entity_name} ({entity_type})."}

    system_instruction = (
        "Tu agis en tant qu'Expert Agile / Product Owner senior. "
        "Ta réponse doit être structurée, premium et directement utilisable dans un outil de gestion de projet. "
        "Réponds UNIQUEMENT avec le contenu textuel généré, sans introduction ni conclusion."
    )

    response = chat.invoke([
        HumanMessage(content=f"{system_instruction}\n\n{prompt}")
    ])
    
    return {"generated_text": response.content.strip()}
