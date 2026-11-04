from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

from .models import Course, CourseModule, CourseState, Section

BASE_URL = "https://ead.puc-rio.br"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class EadAuthError(RuntimeError):
    pass


class EadApiError(RuntimeError):
    pass


@dataclass
class DownloadedFile:
    path: str
    filename: str
    content_type: str
    size_bytes: int


class EadClient:
    def __init__(
        self,
        matricula: str | None = None,
        senha: str | None = None,
        base_url: str = BASE_URL,
        default_download_dir: str | os.PathLike[str] | None = None,
    ):
        self.base_url = base_url
        self.matricula = matricula or os.environ.get("PUCEAD_MATRICULA")
        self.senha = senha or os.environ.get("PUCEAD_SENHA")
        self.default_download_dir = Path(
            default_download_dir or os.environ.get("PUCEAD_DOWNLOAD_DIR") or Path.cwd() / "downloads"
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            follow_redirects=True,
            headers={"User-Agent": UA},
            timeout=httpx.Timeout(30.0, read=120.0),
        )
        self._sesskey: str | None = None
        self._logged_in = False

    async def aclose(self):
        await self._client.aclose()

    # ------------------- auth -------------------
    async def login(self, matricula: str | None = None, senha: str | None = None) -> None:
        if matricula:
            self.matricula = matricula
        if senha:
            self.senha = senha
        if not self.matricula or not self.senha:
            raise EadAuthError(
                "Credenciais ausentes. Defina PUCEAD_MATRICULA/PUCEAD_SENHA ou chame login(matricula, senha)."
            )
        r = await self._client.get("/loginccead/")
        r.raise_for_status()
        m = re.search(r'name="logintoken"\s+value="([^"]+)"', r.text)
        if not m:
            raise EadAuthError("logintoken nao encontrado na pagina de login")
        r = await self._client.post(
            "/login/index.php",
            data={
                "username": self.matricula,
                "password": self.senha,
                "logintoken": m.group(1),
            },
        )
        r.raise_for_status()
        if "/login/" in str(r.url) or "loginerrors" in r.text:
            raise EadAuthError("Login falhou (matricula ou senha incorreta).")
        self._logged_in = True
        self._sesskey = self._extract_sesskey(r.text)

    async def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            await self.login()

    @staticmethod
    def _extract_sesskey(html: str) -> str | None:
        m = re.search(r'"sesskey":"([^"]+)"', html)
        return m.group(1) if m else None

    async def _get_sesskey(self) -> str:
        if self._sesskey:
            return self._sesskey
        r = await self._client.get("/my/")
        r.raise_for_status()
        key = self._extract_sesskey(r.text)
        if not key:
            raise EadApiError("sesskey nao localizada em /my/")
        self._sesskey = key
        return key

    # ------------------- ajax -------------------
    async def ajax(self, methodname: str, args: dict[str, Any]) -> Any:
        await self._ensure_logged_in()
        sesskey = await self._get_sesskey()
        payload = [{"index": 0, "methodname": methodname, "args": args}]
        r = await self._client.post(
            f"/lib/ajax/service.php?sesskey={sesskey}&info={methodname}",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if r.status_code in (401, 403):
            self._sesskey = None
            sesskey = await self._get_sesskey()
            r = await self._client.post(
                f"/lib/ajax/service.php?sesskey={sesskey}&info={methodname}",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        r.raise_for_status()
        body = r.json()
        if not body:
            raise EadApiError(f"{methodname}: resposta vazia")
        row = body[0]
        if row.get("error"):
            raise EadApiError(f"{methodname}: {row['exception'].get('message', 'erro Moodle')}")
        return row["data"]

    # ------------------- high-level -------------------
    async def list_courses(self, classification: str = "all") -> list[Course]:
        """classification in {inprogress, future, past, favourites, hidden, all}."""
        data = await self.ajax(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"classification": classification, "limit": 0, "offset": 0, "sort": "fullname"},
        )
        return [
            Course(
                id=int(c["id"]),
                shortname=c.get("shortname", ""),
                fullname=c.get("fullname", ""),
                viewurl=c.get("viewurl", ""),
                startdate=int(c.get("startdate", 0) or 0),
                enddate=int(c.get("enddate", 0) or 0),
                category=c.get("coursecategory", ""),
            )
            for c in data.get("courses", [])
        ]

    async def get_course_state(self, course_id: int) -> CourseState:
        raw = await self.ajax("core_courseformat_get_state", {"courseid": course_id})
        state = json.loads(raw) if isinstance(raw, str) else raw
        sections = [
            Section(
                id=int(s["id"]),
                number=int(s.get("number", s.get("section", 0))),
                title=s.get("title") or s.get("rawtitle") or "",
                cmlist=[int(x) for x in s.get("cmlist", [])],
                visible=bool(s.get("visible", True)),
            )
            for s in state.get("section", [])
        ]
        modules = [
            CourseModule(
                id=int(cm["id"]),
                name=_unescape(cm.get("name", "")),
                module=cm.get("module", ""),
                modname=cm.get("modname", ""),
                url=cm.get("url", ""),
                sectionid=int(cm.get("sectionid", 0)),
                visible=bool(cm.get("visible", True)),
            )
            for cm in state.get("cm", [])
        ]
        return CourseState(course_id=course_id, sections=sections, modules=modules)

    # ------------------- download -------------------
    async def download_material(
        self,
        cm_id: int,
        *,
        course_id: int | None = None,
        dest_dir: str | os.PathLike[str] | None = None,
    ) -> DownloadedFile:
        """Baixa um resource (ou page com PDF embarcado) para disco.

        Se `course_id` nao for passado, usa a URL `/mod/resource/view.php?id=CM_ID`
        (funciona porque Moodle resolve o cm_id globalmente).
        """
        await self._ensure_logged_in()
        url = f"/mod/resource/view.php?id={cm_id}"
        r = await self._client.get(url)
        r.raise_for_status()

        ct = r.headers.get("content-type", "").lower()
        if "text/html" in ct:
            # resource configurado como embed; procura o link direto
            soup = BeautifulSoup(r.text, "html.parser")
            a = soup.select_one('a[href*="pluginfile.php"]')
            if not a:
                raise EadApiError(f"cm {cm_id}: nao eh resource de arquivo (embed sem link direto)")
            direct = a["href"]
            r = await self._client.get(direct)
            r.raise_for_status()
            ct = r.headers.get("content-type", "").lower()

        filename = _filename_from_response(r)
        target_dir = Path(dest_dir) if dest_dir else self.default_download_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / _safe_filename(filename)
        target.write_bytes(r.content)
        return DownloadedFile(
            path=str(target.resolve()),
            filename=target.name,
            content_type=ct,
            size_bytes=len(r.content),
        )

    async def fetch_page(self, cm_id: int) -> dict[str, Any]:
        """Extrai conteudo de um mod_page. Retorna {'title', 'html', 'text', 'attachments'}."""
        await self._ensure_logged_in()
        r = await self._client.get(f"/mod/page/view.php?id={cm_id}")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        main = soup.select_one("#region-main .no-overflow") or soup.select_one("#region-main")
        title = (soup.select_one("h1, h2") or soup.title)
        attachments = [
            a["href"] for a in (main.select('a[href*="pluginfile.php"]') if main else [])
        ]
        return {
            "title": title.get_text(strip=True) if title else "",
            "html": str(main) if main else "",
            "text": main.get_text("\n", strip=True) if main else "",
            "attachments": attachments,
        }


# ------------------- helpers -------------------
def _filename_from_response(r: httpx.Response) -> str:
    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        return unquote(m.group(1).strip())
    return unquote(str(r.url).rsplit("/", 1)[-1]) or f"download-{r.url.path.replace('/', '_')}"


def _safe_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return name or "arquivo"


def _unescape(s: str) -> str:
    return (
        s.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#039;", "'")
    )
