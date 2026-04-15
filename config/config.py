import os

# --- OpenRouter (LLM) ---
OPENAI_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_BASE = "https://openrouter.ai/api/v1"
LLM_MODEL       = "openai/gpt-4o-mini"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN" ,"")

OWNER = "ilyass-hm-04"
REPO = "Medical-chatbot"
BRANCH = "main"

# --- Filtres de fichiers ---
ALLOWED_EXTENSIONS = (".java", ".py", ".js", ".ts", ".md", ".xml", ".json", ".txt", ".html", ".css", ".tsx", ".jsx")
