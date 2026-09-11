# RAG-Codebase-Agent

AI agent for the **PM-B** project manager. Implements Retrieval-Augmented Generation (RAG) over GitHub repositories: indexes code, retrieves relevant files, and answers natural-language questions about your codebase. Acting as an agent, it creates tasks, sprints, and workspaces directly from repo analysis. Built with Python 3, FastAPI, and OpenRouter LLMs, with Fernet-encrypted tokens.

## 🛠️ Tech Stack

- **Python 3** + **FastAPI**
- **OpenRouter** (LLM provider)
- **RAG** (Retrieval-Augmented Generation) for code understanding
- **Agentic actions** (tool-calling) for task/sprint/workspace creation
- **Fernet** (GitHub token encryption)
- **Uvicorn** (ASGI server)

## ✨ Features

- **GitHub repo analysis** — walks the repository tree and file contents
- **RAG retrieval** — identifies the most relevant files to answer a given question
- **Agentic task generation** — autonomously creates tasks, lists, sprints, and workspaces based on repo analysis
- **Ask AI** — conversational assistant that answers questions about the codebase
- **Secure token handling** — GitHub PATs are encrypted with Fernet before persistence

## 🤖 How it works

1. The agent receives a natural-language request (e.g. "explain this module" or "create sprints for this repo").
2. It retrieves the relevant files/context from the indexed repository (RAG).
3. Depending on the request, it either:
   - answers directly using the retrieved context (**Ask AI**), or
   - takes action by generating and creating project entities — tasks, sprints, workspaces — in the PM-B backend (**agentic mode**).

## 🔐 GitHub Token Security

1. The frontend sends the PAT in plaintext over HTTPS.
2. The AI service immediately encrypts it with Fernet (`ENCRYPTION_KEY`).
3. Only the encrypted version is sent to the Java backend for persistence.
4. On each analysis run, the token is decrypted in memory only — it never travels in plaintext between services.

## 🚀 Quick Start

### Requirements

- Python 3.10+
- pip

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and fill in your values:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `LLM_MODEL` | LLM model (e.g. `openai/gpt-oss-120b:free`) |
| `ENCRYPTION_KEY` | Fernet key (base64) used to encrypt GitHub PATs |
| `BACKEND_BASE_URL` | Spring Boot backend URL |
| `GITHUB_TOKEN` | (optional) GitHub token to avoid rate limiting |

### Run

```bash
uvicorn main:app --reload
```

The API is available at `http://localhost:8000` (Swagger docs at `/docs`).

## 📁 Structure

```
├── main.py              # FastAPI application
├── config/config.py     # Configuration (LLM model, URLs)
└── services/
    ├── github_service.py      # GitHub repository access
    ├── rag_service.py         # RAG, entity generation, Ask AI, agentic actions
    └── encryption_service.py  # Fernet encryption/decryption
```

## 🔗 Related Projects

- [PM-B-backend](https://github.com/jadliaissam-edu/PM-B-backend) — Spring Boot API
- [PM-B-frontend](https://github.com/jadliaissam-edu/PM-B-frontend) — React interface
- [PM-B-infra](https://github.com/jadliaissam-edu/PM-B-infra) — Deployment (Docker, Terraform, Ansible)
