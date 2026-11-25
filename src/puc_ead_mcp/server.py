from __future__ import annotations

import asyncio
import functools
import os
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import EadApiError, EadClient, EadAuthError
from .heuristics import KINDS, classify_material, matches

mcp = MCPServer(
    name="puc-ead",
    instructions=(
        "MCP para coletar slides e provas do EAD da PUC-Rio (Moodle). "
        "Credenciais via env PUCEAD_MATRICULA/PUCEAD_SENHA ou tool login(). "
        "Fluxo típico: list_courses -> search_materials -> download_material."
    ),
)

_client: EadClient | None = None


def _friendly(fn):
    """Converte falhas previstas em ToolError, para a mensagem chegar ao modelo.

    Sem isso o SDK devolve so "Error executing tool X" e o cliente nao sabe se
    foi senha errada, EAD fora do ar ou erro do Moodle.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except (EadAuthError, EadApiError) as e:
            raise ToolError(str(e)) from e
        except httpx.HTTPStatusError as e:
            raise ToolError(f"EAD respondeu HTTP {e.response.status_code} em {e.request.url.path}.") from e
        except httpx.TransportError as e:
            raise ToolError(
                "Nao foi possivel conectar ao EAD (ead.puc-rio.br): rede/DNS indisponivel ou site fora do ar. "
                "Nao e problema de login nem de sessao expirada; tente de novo mais tarde. "
                f"Detalhe: {type(e).__name__}: {e}"
            ) from e

    return wrapper


def _ead() -> EadClient:
    global _client
    if _client is None:
        _client = EadClient()
    return _client


@mcp.tool()
@_friendly
async def login(matricula: str, senha: str) -> dict[str, Any]:
    """Faz login no EAD. Normalmente desnecessário (env vars autoriza no startup)."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = EadClient(matricula=matricula, senha=senha)
    await _client.login()
    return {"ok": True, "message": "Logado."}


@mcp.tool()
@_friendly
async def list_courses(classification: str = "inprogress") -> list[dict[str, Any]]:
    """Lista matérias do usuário. classification: inprogress|future|past|favourites|all."""
    courses = await _ead().list_courses(classification=classification)
    return [c.to_dict() for c in courses]


@mcp.tool()
@_friendly
async def get_course_structure(course_id: int) -> dict[str, Any]:
    """Retorna árvore do curso: seções + módulos (id, nome, tipo, url)."""
    state = await _ead().get_course_state(course_id)
    return state.to_dict()


@mcp.tool()
@_friendly
async def search_materials(
    course_id: int,
    query: str = "",
    kind: str | None = None,
    module_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Busca módulos num curso.

    Args:
        course_id: id do curso.
        query: substring case-insensitive em cm.name ou section.title.
        kind: 'slide' | 'prova' | 'lista' | 'tarefa' (aplica heuristica).
        module_types: filtra por tipo Moodle, ex ['resource', 'page']. Default: todos.
    """
    if kind and kind not in KINDS:
        raise ValueError(f"kind invalido: {kind}. Use um de {KINDS}.")
    state = await _ead().get_course_state(course_id)
    section_title = {s.id: s.title for s in state.sections}
    q = query.lower()
    out: list[dict[str, Any]] = []
    for cm in state.modules:
        st = section_title.get(cm.sectionid, "")
        if query and q not in cm.name.lower() and q not in st.lower():
            continue
        if kind and not matches(cm.name, st, kind):
            continue
        if module_types and cm.module not in module_types:
            continue
        item = cm.to_dict()
        item["section_title"] = st
        item["kind_guess"] = classify_material(cm.name, st)
        out.append(item)
    return out


@mcp.tool()
@_friendly
async def download_material(cm_id: int, dest_dir: str | None = None) -> dict[str, Any]:
    """Baixa um resource. Retorna {path, filename, content_type, size_bytes}."""
    f = await _ead().download_material(cm_id, dest_dir=dest_dir)
    return {
        "path": f.path,
        "filename": f.filename,
        "content_type": f.content_type,
        "size_bytes": f.size_bytes,
    }


async def _bulk_by_kind(course_id: int, kind: str, dest_dir: str | None) -> dict[str, Any]:
    ead = _ead()
    state = await ead.get_course_state(course_id)
    section_title = {s.id: s.title for s in state.sections}
    target_dir = Path(dest_dir) if dest_dir else ead.default_download_dir / f"curso_{course_id}" / kind
    target_dir.mkdir(parents=True, exist_ok=True)

    hits = [
        cm for cm in state.modules
        if cm.module == "resource" and matches(cm.name, section_title.get(cm.sectionid, ""), kind)
    ]
    downloaded: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for cm in hits:
        try:
            f = await ead.download_material(cm.id, dest_dir=target_dir)
            downloaded.append({
                "cm_id": cm.id, "name": cm.name, "path": f.path, "size_bytes": f.size_bytes,
            })
        except Exception as e:
            errors.append({"cm_id": cm.id, "name": cm.name, "error": str(e)})
    return {"dir": str(target_dir), "count": len(downloaded), "downloaded": downloaded, "errors": errors}


@mcp.tool()
@_friendly
async def download_all_slides(course_id: int, dest_dir: str | None = None) -> dict[str, Any]:
    """Baixa todos resources classificados como slide. Retorna lista com paths."""
    return await _bulk_by_kind(course_id, "slide", dest_dir)


@mcp.tool()
@_friendly
async def download_all_provas(course_id: int, dest_dir: str | None = None) -> dict[str, Any]:
    """Baixa todos resources classificados como prova. Retorna lista com paths."""
    return await _bulk_by_kind(course_id, "prova", dest_dir)


@mcp.tool()
@_friendly
async def get_page_content(cm_id: int, as_text: bool = True) -> dict[str, Any]:
    """Extrai conteudo de um mod_page. as_text=True retorna texto; False retorna HTML."""
    page = await _ead().fetch_page(cm_id)
    if as_text:
        return {"title": page["title"], "text": page["text"], "attachments": page["attachments"]}
    return page


async def _main() -> None:
    try:
        ead = _ead()
        if ead.matricula and ead.senha:
            try:
                await ead.login()
            except Exception:
                # Senha errada ou EAD/rede fora do ar: sobe mesmo assim;
                # as tools tentam logar de novo na primeira chamada.
                pass
        await mcp.run_stdio_async()
    finally:
        global _client
        if _client is not None:
            await _client.aclose()


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()
