# PM-B IA Service

Service d'intelligence artificielle du gestionnaire de projet **PM-B**. Il analyse des dépôts GitHub, répond à des questions sur le code et génère des entités de projet (tâches, listes, sprints) à partir du contenu d'un dépôt.

## 🛠️ Stack technique

- **Python 3** + **FastAPI**
- **OpenRouter** (LLM)
- **RAG vectoriel** : chunking + embeddings + **Chroma** (recherche par similarité)
- **Fernet** (chiffrement des tokens GitHub)
- **Uvicorn** (serveur ASGI)

## ✨ Fonctionnalités

- **Analyse de dépôts GitHub** : parcours de l'arborescence et du contenu des fichiers
- **RAG vectoriel** : indexation des fichiers dans Chroma et récupération des chunks les plus pertinents
- **Génération d'entités** : création automatique de tâches/listes/sprints à partir d'un dépôt
- **Ask AI** : assistant conversationnel sur le contenu d'un dépôt
- **Chiffrement sécurisé** : les tokens GitHub (PAT) sont chiffrés avec Fernet avant persistance

## 🔍 RAG vectoriel (pipeline)

1. **Chunking** — découpage intelligent selon le langage :
   - **Python (`.py`)** : parsing **AST** (`ast`) → une unité par fonction, classe et méthode,
     avec signature, docstring et numéros de ligne. Les symboles sont nommés qualifiés
     (`MaClasse.ma_methode`) pour un contexte plus précis.
   - **Autres langages (Java/JS/TS…)** : découpage textuel par frontières de blocs
     (`class` / `function` / `method`), avec fallback sur le fichier brut.
   - Un symbole trop volumineux est re-découpé par `RecursiveCharacterTextSplitter`.
2. **Embeddings** — chaque chunk devient un vecteur :
   - `EMBEDDING_PROVIDER=local` (défaut) : `sentence-transformers` (`all-MiniLM-L6-v2`), gratuit et hors ligne.
   - `EMBEDDING_PROVIDER=openrouter` : embeddings via l'API OpenRouter.
3. **Indexation** — les vecteurs sont stockés dans une collection **Chroma** persistante,
   une collection par dépôt (`owner/repo@branch`), avec métadonnées
   (`symbol`, `kind`, `start_line`, `end_line`).
4. **Retrieval** — `similarity_search(query)` remplace l'ancienne sélection de fichiers par LLM.
   Le contexte transmis au LLM est annoté : `fichier.py::symbole (L12-40)`.
5. **Ré-indexation** — le SHA du dernier commit (`get_latest_commit`) est stocké dans la collection ;
   si le commit change, l'index est automatiquement reconstruit au prochain appel.

## 🔐 Sécurité des tokens GitHub

1. Le frontend envoie le PAT en clair via HTTPS.
2. Le service IA le chiffre immédiatement avec Fernet (`ENCRYPTION_KEY`).
3. Seule la version chiffrée est envoyée au backend Java pour persistance.
4. À chaque analyse, le token est déchiffré en RAM uniquement — il ne transite jamais en clair entre services.

## 🚀 Démarrage rapide

### Prérequis

- Python 3.10+
- pip

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Copiez `.env.example` vers `.env` et renseignez vos valeurs :

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Clé API OpenRouter |
| `LLM_MODEL` | Modèle LLM (ex. `openai/gpt-oss-120b:free`) |
| `ENCRYPTION_KEY` | Clé Fernet (base64) pour chiffrer les PAT GitHub |
| `BACKEND_BASE_URL` | URL du backend Spring Boot |
| `GITHUB_TOKEN` | (optionnel) Token GitHub pour éviter le rate limit |
| `EMBEDDING_PROVIDER` | `local` (défaut, gratuit) ou `openrouter` |
| `EMBEDDING_MODEL_LOCAL` | Modèle sentence-transformers (défaut `all-MiniLM-L6-v2`) |
| `EMBEDDING_MODEL_REMOTE` | Modèle d'embedding OpenRouter (si provider `openrouter`) |
| `CHROMA_PERSIST_DIR` | Dossier de persistance de l'index Chroma (défaut `./.chroma`) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Taille et chevauchement des chunks (défaut `1000` / `150`) |
| `RAG_TOP_K` | Nombre de chunks remontés par la recherche (défaut `8`) |

### Lancer

```bash
uvicorn main:app --reload
```

L'API est disponible sur `http://localhost:8000` (docs Swagger sur `/docs`).

## 📁 Structure

```
├── main.py              # Application FastAPI
├── config/config.py     # Configuration (modèle LLM, embeddings, URLs)
└── services/
    ├── github_service.py      # Accès aux dépôts GitHub
    ├── code_parser.py         # Extraction AST (Python) / blocs (autres langages)
    ├── embedding_service.py   # Chunking, embeddings, index Chroma, retrieval
    ├── rag_service.py         # RAG, génération d'entités, Ask AI
    └── encryption_service.py  # Chiffrement/déchiffrement Fernet
```

## 🔗 Projets liés

- [PM-B-backend](https://github.com/jadliaissam-edu/PM-B-backend) — API Spring Boot
- [PM-B-frontend](https://github.com/jadliaissam-edu/PM-B-frontend) — interface React
- [PM-B-infra](https://github.com/jadliaissam-edu/PM-B-infra) — déploiement (Docker, Terraform, Ansible)
