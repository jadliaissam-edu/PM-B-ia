"""
agent_service.py
----------------
Boucle agentique (tool-calling) pour la generation d'entites.

Principe
========
Contrairement a un simple appel LLM "one-shot", un agent :
  1. recoit une question,
  2. decide LUI-MEME quels outils appeler et dans quel ordre,
  3. observe le resultat de chaque outil,
  4. repete jusqu'a pouvoir repondre (ou jusqu'a la limite d'iterations).

Deux familles d'outils :
  - Outils de LECTURE (search_code, list_known_context) : executes
    automatiquement, sans intervention humaine. C'est la partie "agentique".
  - Outils d'ECRITURE (propose_create_*) : ne creent RIEN. Ils retournent une
    proposition structuree que le frontend affiche a l'utilisateur pour
    confirmation. La creation reelle reste declenchee par l'humain.

Securite :
  - AGENT_MAX_ITERATIONS borne la boucle (anti-boucle infinie).
  - Aucun outil n'ecrit en base : l'agent ne peut pas modifier le projet seul.
"""

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from config.config import (
    AGENT_MAX_ITERATIONS,
    LLM_MODEL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    RAG_TOP_K,
)
from services.embedding_service import search_many

# -----------------------------------------------------------------
# Etat d'execution (injecte par appel, pas de variable globale mutable)
# -----------------------------------------------------------------


class AgentContext:
    """Contexte d'un run agentique : depots indexes + IDs deja connus."""

    def __init__(self, repo_keys: list[str], known_context: dict | None = None):
        self.repo_keys = repo_keys or []
        self.known_context = known_context or {}
        # Propositions de creation accumulees pendant le run (confirmation humaine).
        self.proposals: list[dict] = []


# -----------------------------------------------------------------
# Outils de LECTURE (auto-executes)
# -----------------------------------------------------------------

def _build_tools(ctx: AgentContext) -> list:
    """Construit les outils lies au contexte d'execution courant."""

    @tool
    def search_code(query: str) -> str:
        """Recherche dans le code indexe des depots GitHub les extraits les plus
        pertinents pour une question. Utilise cet outil pour explorer le code,
        comprendre l'architecture, ou trouver des fonctions/classes existantes.
        Tu peux l'appeler plusieurs fois avec des requetes differentes."""
        if not ctx.repo_keys:
            return "Aucun depot indexe : impossible de rechercher dans le code."
        hits = search_many(ctx.repo_keys, query, top_k=RAG_TOP_K)
        if not hits:
            return "Aucun extrait de code pertinent trouve."
        lines = []
        for h in hits:
            header = f"[{h['repo_key']}] {h['path']}::{h.get('symbol', '<file>')} (L{h.get('start_line')}-{h.get('end_line')})"
            lines.append(f"{header}\n{h['content'][:1200]}")
        return "\n\n---\n\n".join(lines)

    @tool
    def list_known_context() -> str:
        """Retourne les identifiants deja connus (workspaceId, spaceId, listeId,
        sprintId, folderId, membres...). Appelle cet outil avant de proposer une
        creation pour savoir quels IDs parent sont disponibles."""
        if not ctx.known_context:
            return "Aucun contexte connu (aucun ID parent disponible)."
        return json.dumps(ctx.known_context, ensure_ascii=False, indent=2)

    return [search_code, list_known_context]


# -----------------------------------------------------------------
# Outils d'ECRITURE (proposition uniquement -> confirmation humaine)
# -----------------------------------------------------------------

def _build_proposal_tools(ctx: AgentContext) -> list:
    """Outils qui ne creent rien : ils enregistrent une proposition."""

    def _propose(intent: str, endpoint: str, entity: dict) -> str:
        # Complete l'entite avec les IDs deja connus si absents.
        for key in ("listeId", "spaceId", "workspaceId", "sprintId", "folderId"):
            if key in ctx.known_context and key not in entity:
                entity[key] = ctx.known_context[key]
        ctx.proposals.append({"intent": intent, "endpoint": endpoint, "entity": entity})
        return (
            f"Proposition de creation '{intent}' enregistree. "
            "Elle sera presentee a l'utilisateur pour confirmation."
        )

    @tool
    def propose_create_task(title: str, description: str = "", status: str = "TO_DO",
                            priority: str = "MEDIUM", dueDate: str = "",
                            listeId: str = "", sprintId: str = "", assigneeId: str = "") -> str:
        """Propose la creation d'une TACHE. Ne cree rien : enregistre une proposition
        soumise a confirmation humaine. Fournis un titre clair et une description
        detaillee du travail a accomplir."""
        entity: dict[str, Any] = {"title": title, "status": status, "priority": priority}
        if description:
            entity["description"] = description
        for k, v in (("dueDate", dueDate), ("listeId", listeId),
                     ("sprintId", sprintId), ("assigneeId", assigneeId)):
            if v:
                entity[k] = v
        return _propose("task", "POST /api/tasks", entity)

    @tool
    def propose_create_sprint(name: str, goal: str = "", startDate: str = "",
                              endDate: str = "", spaceId: str = "") -> str:
        """Propose la creation d'un SPRINT. Ne cree rien : enregistre une proposition
        soumise a confirmation humaine. Fournis un objectif de sprint pertinent."""
        entity: dict[str, Any] = {"name": name}
        for k, v in (("goal", goal), ("startDate", startDate),
                     ("endDate", endDate), ("spaceId", spaceId)):
            if v:
                entity[k] = v
        return _propose("sprint", "POST /api/sprints", entity)

    @tool
    def propose_create_workspace(name: str, slug: str = "") -> str:
        """Propose la creation d'un WORKSPACE. Ne cree rien : enregistre une
        proposition soumise a confirmation humaine."""
        entity: dict[str, Any] = {"name": name}
        if slug:
            entity["slug"] = slug
        return _propose("workspace", "POST /api/workspaces", entity)

    @tool
    def propose_create_space(name: str, description: str = "", workspaceId: str = "") -> str:
        """Propose la creation d'un SPACE (espace). Ne cree rien : enregistre une
        proposition soumise a confirmation humaine."""
        entity: dict[str, Any] = {"name": name}
        for k, v in (("description", description), ("workspaceId", workspaceId)):
            if v:
                entity[k] = v
        return _propose("space", "POST /api/spaces", entity)

    @tool
    def propose_create_folder(name: str, description: str = "", spaceId: str = "") -> str:
        """Propose la creation d'un DOSSIER (folder). Ne cree rien : enregistre une
        proposition soumise a confirmation humaine."""
        entity: dict[str, Any] = {"name": name}
        for k, v in (("description", description), ("spaceId", spaceId)):
            if v:
                entity[k] = v
        return _propose("folder", "POST /api/folders", entity)

    @tool
    def propose_create_liste(name: str, type: str = "SPRINT", order: int = 0,
                             folderId: str = "", sprintId: str = "") -> str:
        """Propose la creation d'une LISTE. Ne cree rien : enregistre une proposition
        soumise a confirmation humaine. 'type' vaut SPRINT ou PHASE."""
        entity: dict[str, Any] = {"name": name, "type": type, "order": order}
        for k, v in (("folderId", folderId), ("sprintId", sprintId)):
            if v:
                entity[k] = v
        return _propose("liste", "POST /api/listes", entity)

    return [
        propose_create_task,
        propose_create_sprint,
        propose_create_workspace,
        propose_create_space,
        propose_create_folder,
        propose_create_liste,
    ]


# -----------------------------------------------------------------
# Prompt systeme de l'agent
# -----------------------------------------------------------------

_SYSTEM_PROMPT = (
    "Tu es un agent IA de gestion de projet, connecte a un depot de code GitHub.\n\n"
    "Tu disposes d'outils :\n"
    "- search_code : recherche dans le code indexe du depot.\n"
    "- list_known_context : liste les IDs deja connus (workspace, space, sprint...).\n"
    "- propose_create_* : propose la creation d'une entite (tache, sprint, workspace, "
    "space, dossier, liste).\n\n"
    "REGLES :\n"
    "1. Si la demande porte sur le code (comprendre une fonctionnalite, trouver un bug, "
    "expliquer l'architecture), utilise search_code autant de fois que necessaire, avec "
    "des requetes differentes, avant de repondre.\n"
    "2. Si la demande est de CREER une ou plusieurs entites, appelle les outils "
    "propose_create_* correspondants. Tu peux enchainer plusieurs propositions "
    "(ex: Workspace -> Space -> Folder -> Liste -> Task).\n"
    "3. Les outils propose_create_* ne creent RIEN : ils enregistrent une proposition "
    "que l'utilisateur confirmera. Ne dis donc jamais que la creation est faite.\n"
    "4. Pour une tache, fournis toujours une description detaillee. Pour un sprint, "
    "fournis toujours un objectif (goal).\n"
    "5. Si une entite depend d'un parent cree dans le meme flux, laisse l'ID vide : "
    "le frontend le pre-remplira.\n"
    "6. Quand tu as termine, reponds en Francais, de facon naturelle et professionnelle. "
    "Ne mentionne JAMAIS d'endpoint API, d'URL, de JSON ou de details techniques.\n"
)


# -----------------------------------------------------------------
# Boucle agentique
# -----------------------------------------------------------------

def _extract_text(content: Any) -> str:
    """Normalise le contenu d'un message (str ou liste de blocs) en texte."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content or "")


def run_agent(user_query: str, repo_keys: list[str],
              known_context: dict | None = None) -> dict:
    """
    Execute la boucle agentique et retourne :
      {
        "flow": [ {intent, endpoint, entity}, ... ],   # propositions a confirmer
        "explanation": "message pour l'utilisateur",
        "steps": [ "search_code(...)", ... ],          # trace des outils appeles
        "agentic": True
      }
    """
    ctx = AgentContext(repo_keys, known_context)
    tools = _build_tools(ctx) + _build_proposal_tools(ctx)
    tools_by_name = {t.name: t for t in tools}

    llm = ChatOpenAI(
        model_name=LLM_MODEL,
        openai_api_key=OPENAI_API_KEY,
        openai_api_base=OPENAI_API_BASE,
    )
    llm_with_tools = llm.bind_tools(tools)

    messages: list = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_query),
    ]
    steps: list[str] = []
    final_text = ""

    for _ in range(AGENT_MAX_ITERATIONS):
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            final_text = _extract_text(response.content).strip()
            break

        for call in tool_calls:
            name = call.get("name")
            args = call.get("args", {}) or {}
            steps.append(f"{name}({json.dumps(args, ensure_ascii=False)})")

            tool_fn = tools_by_name.get(name)
            if tool_fn is None:
                result = f"Outil inconnu : {name}"
            else:
                try:
                    result = tool_fn.invoke(args)
                except Exception as exc:  # un outil qui echoue ne doit pas tuer le run
                    result = f"Erreur de l'outil {name} : {exc}"

            messages.append(ToolMessage(content=str(result), tool_call_id=call.get("id")))

    if not final_text:
        final_text = (
            "J'ai analyse votre demande. Verifiez les propositions ci-dessous "
            "avant de confirmer."
        )

    # Nettoyage : retirer un eventuel bloc markdown residuel.
    final_text = re.sub(r"^```[a-z]*\n?", "", final_text)
    final_text = re.sub(r"\n?```$", "", final_text).strip()

    return {
        "flow": ctx.proposals,
        "explanation": final_text,
        "steps": steps,
        "agentic": True,
    }
