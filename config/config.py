"""
config.py
---------
Chargement centralisé de la configuration depuis le fichier .env.
Toutes les valeurs sensibles (clés API, clé de chiffrement) sont
exclusivement chargées via des variables d'environnement.
"""

import os
from dotenv import load_dotenv

# Charge les variables depuis config/.env
load_dotenv()

# ─── LLM (OpenRouter) ────────────────────────────────────────────────────────
OPENAI_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_BASE = "https://openrouter.ai/api/v1"
LLM_MODEL       = os.getenv("LLM_MODEL", "openai/gpt-oss-120b:free")

# ─── Embeddings (RAG vectoriel) ──────────────────────────────────────────────
# EMBEDDING_PROVIDER :
#   "local"      -> sentence-transformers, 100% gratuit, tourne en local (defaut)
#   "openrouter" -> embeddings via OpenRouter (necessite OPENROUTER_API_KEY)
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").lower()

# Modele d'embedding local (sentence-transformers). all-MiniLM-L6-v2 = 384 dims,
# ~80 Mo, rapide et suffisant pour du code/documentation.
EMBEDDING_MODEL_LOCAL = os.getenv("EMBEDDING_MODEL_LOCAL", "all-MiniLM-L6-v2")

# Modele d'embedding distant (utilise uniquement si EMBEDDING_PROVIDER=openrouter).
EMBEDDING_MODEL_REMOTE = os.getenv("EMBEDDING_MODEL_REMOTE", "openai/text-embedding-3-small")

# ─── Index vectoriel Chroma ──────────────────────────────────────────────────
# Repertoire de persistance de l'index Chroma (un dossier par depot).
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./.chroma")

# Decoupage des fichiers en chunks avant embedding.
CHUNK_SIZE    = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))

# Nombre de chunks remontes par la recherche vectorielle.
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))

# ─── Agent (tool-calling) ────────────────────────────────────────────────────
# AGENT_ENABLED : active la boucle agentique (tool-calling) pour /api/ia/generate.
#   "true"  -> l'agent choisit lui-meme les outils (recherche code, lecture fichier)
#              et propose des creations d'entites (confirmation humaine requise).
#   "false" -> comportement historique : un seul appel LLM qui retourne le JSON.
# Desactivable car tous les modeles ne supportent pas le tool-calling de facon fiable.
AGENT_ENABLED = os.getenv("AGENT_ENABLED", "true").lower() in ("1", "true", "yes", "on")

# Nombre maximal d'iterations de la boucle agentique (garde-fou anti-boucle infinie).
AGENT_MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "6"))

# ─── Filtres de fichiers GitHub ───────────────────────────────────────────────
ALLOWED_EXTENSIONS = (
    ".java", ".py", ".js", ".ts", ".md", ".xml",
    ".json", ".txt", ".html", ".css", ".tsx", ".jsx"
)

# ─── Chiffrement des PAT GitHub ──────────────────────────────────────────────
# La clé Fernet est chargée depuis ENCRYPTION_KEY dans .env.
# Ne jamais définir de valeur par défaut ici — l'absence de clé doit être
# détectée immédiatement par encryption_service.py.
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

# ─── Backend Java Spring Boot ────────────────────────────────────────────────
# URL de base du backend Spring Boot (PM-B-backend) pour la persistance des dépôts.
BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8080")
