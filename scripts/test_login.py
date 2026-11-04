"""Smoke test: pode logar com httpx puro (sem browser)?

Valida se reCAPTCHA v3 bloqueia login programatico. Se este script
imprimir 'LOGIN OK + courses:N', o MCP pode usar httpx direto.
"""
import os
import re
import sys
import httpx

BASE = "https://ead.puc-rio.br"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def login(matricula: str, senha: str) -> httpx.Client:
    client = httpx.Client(
        base_url=BASE,
        follow_redirects=True,
        headers={"User-Agent": UA},
        timeout=30.0,
    )
    r = client.get("/loginccead/")
    r.raise_for_status()
    m = re.search(r'name="logintoken"\s+value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("logintoken nao encontrado na pagina de login")
    logintoken = m.group(1)

    r = client.post(
        "/login/index.php",
        data={"username": matricula, "password": senha, "logintoken": logintoken},
    )
    r.raise_for_status()
    if "loginerrors" in r.text or "/login/" in str(r.url):
        raise RuntimeError(f"Login falhou. URL final: {r.url}")
    return client


def get_sesskey(client: httpx.Client) -> str:
    r = client.get("/my/")
    r.raise_for_status()
    m = re.search(r'"sesskey":"([^"]+)"', r.text)
    if not m:
        raise RuntimeError("sesskey nao encontrada")
    return m.group(1)


def ajax(client: httpx.Client, sesskey: str, methodname: str, args: dict):
    r = client.post(
        f"/lib/ajax/service.php?sesskey={sesskey}&info={methodname}",
        json=[{"index": 0, "methodname": methodname, "args": args}],
        headers={"Content-Type": "application/json"},
    )
    r.raise_for_status()
    body = r.json()[0]
    if body.get("error"):
        raise RuntimeError(f"{methodname}: {body['exception']['message']}")
    return body["data"]


def main():
    matricula = os.environ.get("PUCEAD_MATRICULA") or sys.argv[1]
    senha = os.environ.get("PUCEAD_SENHA") or sys.argv[2]
    client = login(matricula, senha)
    print(f"LOGIN OK. Cookies: {[c.name for c in client.cookies.jar]}")
    sesskey = get_sesskey(client)
    print(f"sesskey: ...{sesskey[-4:]}")
    courses = ajax(
        client, sesskey,
        "core_course_get_enrolled_courses_by_timeline_classification",
        {"classification": "inprogress", "limit": 0, "offset": 0, "sort": "fullname"},
    )["courses"]
    print(f"courses:{len(courses)}")
    for c in courses:
        print(f"  [{c['id']}] {c['shortname']}")


if __name__ == "__main__":
    main()
