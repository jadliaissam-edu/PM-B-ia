# PM-B IA Service

Service d'intelligence artificielle du gestionnaire de projet **PM-B**. Il analyse des dépôts GitHub, répond à des questions sur le code et génère des entités de projet (tâches, listes, sprints) à partir du contenu d'un dépôt.

## 🛠️ Stack technique

- **Python 3** + **FastAPI**
- **OpenRouter** (LLM)
- **RAG** (retrieval-augmented generation) pour l'analyse de code
- **Fernet** (chiffrement des tokens GitHub)
- **Uvicorn** (serveur ASGI)

## ✨ Fonctionnalités

- **Analyse de dépôts GitHub** : parcours de l'arborescence et du contenu des fichiers
- **RAG** : identification des fichiers pertinents pour répondre à une question
- **Génération d'entités** : création automatique de tâches/listes/sprints à partir d'un dépôt
- **Ask AI** : assistant conversationnel sur le contenu d'un dépôt
- **Chiffrement sécurisé** : les tokens GitHub (PAT) sont chiffrés avec Fernet avant persistance

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

### Lancer

```bash
uvicorn main:app --reload
```

L'API est disponible sur `http://localhost:8000` (docs Swagger sur `/docs`).

## 📁 Structure

```
├── main.py              # Application FastAPI
├── config/config.py     # Configuration (modèle LLM, URLs)
└── services/
    ├── github_service.py      # Accès aux dépôts GitHub
    ├── rag_service.py         # RAG, génération d'entités, Ask AI
    └── encryption_service.py  # Chiffrement/déchiffrement Fernet
```

## 🔗 Projets liés

- [PM-B-backend](https://github.com/jadliaissam-edu/PM-B-backend) — API Spring Boot
- [PM-B-frontend](https://github.com/jadliaissam-edu/PM-B-frontend) — interface React
- [PM-B-infra](https://github.com/jadliaissam-edu/PM-B-infra) — déploiement (Docker, Terraform, Ansible)
