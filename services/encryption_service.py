"""
encryption_service.py
---------------------
Chiffrement symétrique Fernet (AES-128-CBC + HMAC-SHA256) pour les Personal
Access Tokens (PAT) GitHub stockés en base de données.

Règles de sécurité respectées :
  - La clé ne vit JAMAIS en base de données ; elle est uniquement chargée
    depuis la variable d'environnement ENCRYPTION_KEY (.env du serveur).
  - Le chiffrement se fait entièrement en mémoire vive (RAM).
  - Un token sans clé ne peut pas être déchiffré.
"""

import os
from cryptography.fernet import Fernet, InvalidToken


def _load_fernet() -> Fernet:
    """
    Charge la clé Fernet depuis l'environnement.
    Lève une RuntimeError claire si la clé est absente ou invalide.
    """
    key = os.getenv("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY est absente du fichier .env. "
            "Générez-en une avec : python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError(f"ENCRYPTION_KEY invalide : {exc}") from exc


def encrypt_token(plain_token: str) -> str:
    """
    Chiffre un token GitHub en clair et retourne une chaîne base64 sécurisée.

    Args:
        plain_token: Le Personal Access Token GitHub en clair.

    Returns:
        La représentation chiffrée (str UTF-8), prête à être stockée en BDD.

    Raises:
        RuntimeError: Si ENCRYPTION_KEY est absente ou invalide.
        ValueError:   Si plain_token est vide.
    """
    if not plain_token or not plain_token.strip():
        raise ValueError("Le token à chiffrer ne peut pas être vide.")

    fernet = _load_fernet()
    encrypted_bytes = fernet.encrypt(plain_token.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    """
    Déchiffre un token GitHub stocké en base de données.
    Le déchiffrement s'effectue uniquement en mémoire vive.

    Args:
        encrypted_token: La chaîne chiffrée telle que stockée en BDD.

    Returns:
        Le Personal Access Token GitHub en clair (str).

    Raises:
        RuntimeError:  Si ENCRYPTION_KEY est absente ou invalide.
        ValueError:    Si encrypted_token est vide ou corrompu.
    """
    if not encrypted_token or not encrypted_token.strip():
        raise ValueError("Le token chiffré ne peut pas être vide.")

    fernet = _load_fernet()
    try:
        decrypted_bytes = fernet.decrypt(encrypted_token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Impossible de déchiffrer le token : clé incorrecte ou données corrompues."
        ) from exc


def generate_new_key() -> str:
    """
    Génère une nouvelle clé Fernet prête à être copiée dans .env.
    À appeler UNE SEULE FOIS lors de l'installation.

    Returns:
        Une clé Fernet valide (str).
    """
    return Fernet.generate_key().decode("utf-8")
