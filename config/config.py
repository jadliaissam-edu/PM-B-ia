import os
from dotenv import load_dotenv

load_dotenv()

# --- OpenRouter (LLM) ---
OPENAI_API_KEY  = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_BASE = "https://openrouter.ai/api/v1"
LLM_MODEL       = "openai/gpt-oss-120b:free"


# --- Filtres de fichiers ---
ALLOWED_EXTENSIONS = (".java", ".py", ".js", ".ts", ".md", ".xml", ".json", ".txt", ".html", ".css", ".tsx", ".jsx")
