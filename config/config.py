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
LLM_MODEL       = "openai/gpt-oss-120b:free"

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
