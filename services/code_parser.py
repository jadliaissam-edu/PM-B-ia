"""
code_parser.py
--------------
Extraction structurelle du code avant indexation RAG.

Pour les fichiers Python (.py), on utilise le module standard `ast` afin
d'extraire des unites semantiques (fonctions, classes, methodes) avec leur
signature et leur docstring, au lieu d'indexer le fichier brut tronque.

Pour les autres langages (Java, JS/TS, etc.), on retombe sur un decoupage
textuel par frontieres de blocs (class / function / method).

Chaque unite produite est un dict :
    {
        "content":  texte a indexer (signature + docstring + corps),
        "symbol":   nom qualifie (ex. "MaClasse.ma_methode"),
        "kind":     "function" | "class" | "method" | "module" | "block",
        "start":    ligne de debut (1-based),
        "end":      ligne de fin (1-based),
    }
"""

import ast
import re

# Taille maximale d'un corps de symbole indexe (caracteres).
# Au-dela, on tronque pour eviter des chunks geants.
_MAX_SYMBOL_CHARS = 4000

# Taille maximale d'un bloc pour les langages non-Python.
_MAX_BLOCK_CHARS = 2000


# ─── Python : extraction via `ast` ───────────────────────────────────────────

def _signature(node: ast.AST, source_lines: list[str]) -> str:
    """
    Reconstruit la signature d'une fonction/classe a partir du code source
    (de la ligne `def`/`class` jusqu'au ':' final, en gerant le multi-ligne).
    """
    start = node.lineno - 1
    end = getattr(node, "body", [None])[0]
    end_line = (end.lineno - 1) if end is not None else start

    # On remonte jusqu'a la ligne contenant le ':' de fin de signature.
    collected: list[str] = []
    for i in range(start, min(end_line + 1, len(source_lines))):
        collected.append(source_lines[i])
        if source_lines[i].rstrip().endswith(":"):
            break

    signature = "\n".join(collected).strip()
    # Nettoyage : on retire le ':' final et on normalise les espaces.
    signature = re.sub(r":\s*$", "", signature)
    return re.sub(r"\s+", " ", signature).strip()


def _docstring(node: ast.AST) -> str:
    """Retourne la docstring nettoyee d'un noeud, ou une chaine vide."""
    doc = ast.get_docstring(node, clean=True)
    return doc.strip() if doc else ""


def _node_source(node: ast.AST, source_lines: list[str]) -> str:
    """Extrait le code source brut d'un noeud (bornes 1-based incluses)."""
    start = node.lineno - 1
    end = getattr(node, "end_lineno", node.lineno)
    return "\n".join(source_lines[start:end])


def _render_symbol(
    node: ast.AST,
    source_lines: list[str],
    symbol: str,
    kind: str,
) -> dict:
    """
    Construit l'unite indexable d'un symbole : signature + docstring + corps.
    """
    signature = _signature(node, source_lines)
    doc = _docstring(node)
    body = _node_source(node, source_lines)

    parts = [f"# {kind}: {symbol}"]
    if signature:
        parts.append(signature)
    if doc:
        parts.append(f'"""{doc}"""')
    parts.append(body)

    content = "\n".join(parts).strip()
    if len(content) > _MAX_SYMBOL_CHARS:
        content = content[:_MAX_SYMBOL_CHARS] + "\n# ... (tronque)"

    return {
        "content": content,
        "symbol": symbol,
        "kind": kind,
        "start": node.lineno,
        "end": getattr(node, "end_lineno", node.lineno),
    }


def _walk_python(
    node: ast.AST,
    source_lines: list[str],
    prefix: str,
    units: list[dict],
) -> None:
    """
    Parcours recursif de l'AST : extrait fonctions, classes et methodes.
    Les methodes sont nommees "Classe.methode" pour un contexte plus clair.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            symbol = f"{prefix}{child.name}"
            units.append(_render_symbol(child, source_lines, symbol, "class"))
            # On descend dans la classe pour recuperer ses methodes.
            _walk_python(child, source_lines, prefix=f"{symbol}.", units=units)

        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbol = f"{prefix}{child.name}"
            kind = "method" if prefix else "function"
            units.append(_render_symbol(child, source_lines, symbol, kind))
            # Fonctions imbriquees (closures) : on les indexe aussi.
            _walk_python(child, source_lines, prefix=f"{symbol}.", units=units)

        else:
            # On continue a descendre (if/try/with au niveau module).
            _walk_python(child, source_lines, prefix, units)


def parse_python(content: str) -> list[dict]:
    """
    Extrait les unites semantiques d'un fichier Python via `ast`.

    Args:
        content: Contenu source du fichier .py.

    Returns:
        Liste d'unites { content, symbol, kind, start, end }.
        Liste vide si le fichier n'est pas parsable (syntaxe invalide).
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []

    source_lines = content.splitlines()
    units: list[dict] = []

    # Docstring de module : utile pour comprendre le role du fichier.
    module_doc = _docstring(tree)
    if module_doc:
        units.append({
            "content": f"# module docstring\n{module_doc}",
            "symbol": "<module>",
            "kind": "module",
            "start": 1,
            "end": 1,
        })

    _walk_python(tree, source_lines, prefix="", units=units)
    return units


# ─── Autres langages : decoupage par blocs ───────────────────────────────────

# Frontieres de blocs pour Java / JS / TS / C-like.
_BLOCK_START = re.compile(
    r"^\s*(?:"
    r"(?:(?:public|private|protected|static|final|abstract|async|export|default)\s+)*"
    r"(?:class|interface|enum|record|struct|function|func|def)\s+\w+"
    r"|(?:public|private|protected)\s+[\w<>\[\],\s]+\s+\w+\s*\("
    r")"
)


def parse_generic(content: str) -> list[dict]:
    """
    Decoupage textuel d'un fichier non-Python en blocs logiques.

    On coupe a chaque frontiere de classe/fonction/methode detectee, puis on
    tronque les blocs trop longs. Fallback si l'AST n'est pas disponible.

    Args:
        content: Contenu source du fichier.

    Returns:
        Liste d'unites { content, symbol, kind, start, end }.
    """
    lines = content.splitlines()
    if not lines:
        return []

    # Reperer les lignes de debut de bloc.
    boundaries = [i for i, line in enumerate(lines) if _BLOCK_START.match(line)]
    if not boundaries:
        # Aucune frontiere : on renvoie le fichier entier (tronque).
        text = content[:_MAX_BLOCK_CHARS]
        return [{
            "content": text,
            "symbol": "<file>",
            "kind": "block",
            "start": 1,
            "end": len(lines),
        }]

    units: list[dict] = []
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(lines)
        block = "\n".join(lines[start:end]).strip()
        if not block:
            continue

        # Nom du symbole : premier identifiant apres class/function/def.
        match = re.search(r"(?:class|interface|enum|record|struct|function|func|def)\s+(\w+)", block)
        symbol = match.group(1) if match else f"block@{start + 1}"

        if len(block) > _MAX_BLOCK_CHARS:
            block = block[:_MAX_BLOCK_CHARS] + "\n// ... (tronque)"

        units.append({
            "content": block,
            "symbol": symbol,
            "kind": "block",
            "start": start + 1,
            "end": end,
        })

    return units


# ─── Point d'entree ──────────────────────────────────────────────────────────

def parse_file(path: str, content: str) -> list[dict]:
    """
    Extrait les unites indexables d'un fichier selon son extension.

    - `.py`  -> parsing AST (fonctions, classes, methodes, docstrings).
    - autres -> decoupage textuel par blocs (fallback).

    Args:
        path:    Chemin du fichier (utilise pour detecter le langage).
        content: Contenu source.

    Returns:
        Liste d'unites { content, symbol, kind, start, end }.
    """
    if not content or not content.strip():
        return []

    if path.endswith(".py"):
        units = parse_python(content)
        if units:
            return units
        # Fichier Python non parsable -> fallback textuel.
        return parse_generic(content)

    return parse_generic(content)
