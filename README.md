# RAG-Codebase-Agent

AI service for the **PM-B** project manager. Implements Retrieval-Augmented Generation (RAG) over GitHub repositories: indexes code, retrieves relevant chunks, and answers natural-language questions about your codebase. It also runs an **agentic loop** (tool-calling) that explores the code and proposes project entities (tasks, sprints, workspaces) for the user to confirm. Built with Python 3, FastAPI, and OpenRouter LLMs, with Fernet-encrypted tokens.

## 🛠️ Tech Stack

- **Python 3** + **FastAPI**
- **OpenRouter** (LLM provider)
- **Vector RAG** — AST-aware chunking + embeddings + **Chroma** similarity search
- **Agentic loop** — tool-calling (`bind_tools`) with read tools and proposal tools
- **Fernet** (GitHub token encryption)
- **Uvicorn** (ASGI server)

## ✨ Features

- **GitHub repo analysis** — walks the repository tree and file contents
- **Vector RAG retrieval** — indexes code into Chroma and retrieves the most relevant chunks
- **AST-aware code context** — Python files are parsed with `ast` to index functions, classes and methods (with signatures and docstrings) instead of raw truncated files
- **Agentic entity generation** — the agent autonomously calls tools to explore the code and proposes tasks, lists, sprints, and workspaces. Proposals are **never created automatically**: they are returned to the frontend for human confirmation
- **Ask AI** — conversational assistant that answers questions about the codebase
- **Secure token handling** — GitHub PATs are encrypted with Fernet before persistence
- **Incremental re-indexing** — the index is rebuilt only when the repository's latest commit changes

## 🤖 How it works

1. The service receives a natural-language request (e.g. "explain this module" or "create sprints for this repo").
2. It retrieves the relevant code context from the indexed repository (RAG).
3. Depending on the request, it either:
   - answers directly using the retrieved context (**Ask AI**), or
   - runs the **agentic loop**: the LLM decides which tools to call (`search_code`, `list_known_context`, `propose_create_*`), observes the results, and iterates until it can answer.
4. The agent returns a `flow` of **proposals** plus an explanation. The frontend displays them and the user confirms before anything is created in the PM-B backend.

> **Human-in-the-loop by design** — the agent has no write access. Its `propose_create_*` tools only record a structured proposal; the actual creation is triggered by the user.

## 🧠 Agentic Loop

The agent is enabled with `AGENT_ENABLED=true` (default). It runs a bounded tool-calling loop:

```
query → LLM → tool_call? ──no──→ final answer
          ↑         │
          │        yes
          │         ↓
          │    execute tool
          └─────────┘
```

| Tool | Type | Behaviour |
|------|------|-----------|
| `search_code(query)` | read | Vector search over the indexed repositories |
| `list_known_context()` | read | Returns known parent IDs (workspace, space, sprint…) |
| `propose_create_task` | proposal | Records a task proposal (no write) |
| `propose_create_sprint` | proposal | Records a sprint proposal (no write) |
| `propose_create_workspace` | proposal | Records a workspace proposal (no write) |
| `propose_create_space` | proposal | Records a space proposal (no write) |
| `propose_create_folder` | proposal | Records a folder proposal (no write) |
| `propose_create_liste` | proposal | Records a list proposal (no write) |

**Guardrails:**
- `AGENT_MAX_ITERATIONS` (default `6`) bounds the loop to prevent infinite tool-calling.
- A failing tool returns an error message to the model instead of crashing the run.
- If the model does not support tool-calling reliably, set `AGENT_ENABLED=false` to fall back to the single-call JSON generation.

## 🔍 Vector RAG Pipeline

1. **Chunking** — language-aware splitting:
   - **Python (`.py`)** — parsed with the standard `ast` module: one unit per function, class and method,
     including signature, docstring and line numbers. Symbols use qualified names
     (`MyClass.my_method`) for a more precise context.
   - **Other languages (Java/JS/TS…)** — text splitting on block boundaries
     (`class` / `function` / `method`), with a raw-file fallback.
   - Oversized symbols are re-split with `RecursiveCharacterTextSplitter`.
2. **Embeddings** — every chunk becomes a vector:
   - `EMBEDDING_PROVIDER=local` (default) — `sentence-transformers` (`all-MiniLM-L6-v2`), free and offline.
   - `EMBEDDING_PROVIDER=openrouter` — embeddings through the OpenRouter API.
3. **Indexing** — vectors are stored in a persistent **Chroma** collection, one per repository
   (`owner/repo@branch`), with metadata (`symbol`, `kind`, `start_line`, `end_line`).
4. **Retrieval** — `similarity_search(query)` replaces the previous LLM-based file selection.
   The context sent to the LLM is annotated: `file.py::symbol (L12-40)`.
5. **Re-indexing** — the latest commit SHA (`get_latest_commit`) is stored in the collection;
   when the commit changes, the index is automatically rebuilt on the next call.

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

Create a `.env` file (see `PM-B-infra/ia.env.example` for a template) and fill in your values:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `LLM_MODEL` | LLM model (e.g. `openai/gpt-oss-120b:free`) |
| `ENCRYPTION_KEY` | Fernet key (base64) used to encrypt GitHub PATs |
| `BACKEND_BASE_URL` | Spring Boot backend URL |
| `GITHUB_TOKEN` | (optional) GitHub token to avoid rate limiting |
| `EMBEDDING_PROVIDER` | `local` (default, free) or `openrouter` |
| `EMBEDDING_MODEL_LOCAL` | sentence-transformers model (default `all-MiniLM-L6-v2`) |
| `EMBEDDING_MODEL_REMOTE` | OpenRouter embedding model (when provider is `openrouter`) |
| `CHROMA_PERSIST_DIR` | Chroma index persistence folder (default `./.chroma`) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Chunk size and overlap (default `1000` / `150`) |
| `RAG_TOP_K` | Number of chunks returned per search (default `8`) |
| `AGENT_ENABLED` | Enable the agentic tool-calling loop (default `true`) |
| `AGENT_MAX_ITERATIONS` | Max agent loop iterations (default `6`) |

### Run

```bash
uvicorn main:app --reload
```

The API is available at `http://localhost:8000` (Swagger docs at `/docs`).

> **Note** — `sentence-transformers` pulls in PyTorch (~2 GB). To keep the install light,
> set `EMBEDDING_PROVIDER=openrouter` and skip that dependency.

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/ia/repos/add` | Add or update a GitHub repository (encrypts the PAT if private) |
| `POST` | `/api/ia/validate` | Check that a repository exists and is accessible |
| `DELETE` | `/api/ia/repos/delete` | Remove a repository and purge its vector index |
| `POST` | `/api/ia/repos/reindex` | Force a rebuild of the vector index |
| `POST` | `/api/ia/repo` | Answer a question about one or more repositories (vector RAG) |
| `POST` | `/api/ia/generate` | Run the agentic loop and return entity proposals (tasks, sprints…) |
| `POST` | `/api/ia/ask-ai` | Generate a description or sprint goal for an entity |

## 📁 Structure

```
├── main.py              # FastAPI application
├── config/config.py     # Configuration (LLM, embeddings, agent, URLs)
└── services/
    ├── github_service.py      # GitHub repository access
    ├── code_parser.py         # AST extraction (Python) / block splitting (other languages)
    ├── embedding_service.py   # Chunking, embeddings, Chroma index, retrieval
    ├── agent_service.py       # Agentic loop (tool-calling) and proposal tools
    ├── rag_service.py         # RAG answering, entity generation, Ask AI
    └── encryption_service.py  # Fernet encryption/decryption
```

## 🔗 Related Projects

- [PM-B-backend](https://github.com/jadliaissam-edu/PM-B-backend) — Spring Boot API
- [PM-B-frontend](https://github.com/jadliaissam-edu/PM-B-frontend) — React interface
- [PM-B-infra](https://github.com/jadliaissam-edu/PM-B-infra) — Deployment (Docker, Terraform, Ansible)
