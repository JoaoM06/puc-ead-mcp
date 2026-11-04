import re

PATTERNS: dict[str, re.Pattern[str]] = {
    "slide": re.compile(r"\b(slide|slides|aula\s*\d+|cap[íi]tulo\s*\d+|lecture)\b", re.IGNORECASE),
    "prova": re.compile(r"\b(prova|p[12]\b|exame|avalia[çc][ãa]o|gabarito|final)\b", re.IGNORECASE),
    "lista": re.compile(r"\b(lista|exerc[íi]cios?|ficha|homework|hw\d*)\b", re.IGNORECASE),
    "tarefa": re.compile(r"\b(trabalho|projeto|entrega|tarefa|assignment)\b", re.IGNORECASE),
}

KINDS = tuple(PATTERNS.keys())


def classify_material(name: str, section_title: str = "") -> str:
    """Rotula um material como slide/prova/lista/tarefa/other.

    Testa `name` primeiro; se nao bater, tenta `section_title`.
    Prioridade: prova > slide > lista > tarefa (provas podem ter nome genérico).
    """
    hay_name = name or ""
    hay_section = section_title or ""
    for kind in ("prova", "slide", "lista", "tarefa"):
        pat = PATTERNS[kind]
        if pat.search(hay_name) or pat.search(hay_section):
            return kind
    return "other"


def matches(name: str, section_title: str, kind: str) -> bool:
    pat = PATTERNS.get(kind)
    if not pat:
        return False
    return bool(pat.search(name or "") or pat.search(section_title or ""))
