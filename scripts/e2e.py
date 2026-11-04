"""End-to-end: login, lista cursos, busca provas em MAT1320, baixa a primeira."""
import asyncio
import os
import sys

from puc_ead_mcp import EadClient
from puc_ead_mcp.heuristics import matches

MAT1320_ID = 121330


async def main() -> int:
    matricula = os.environ.get("PUCEAD_MATRICULA") or sys.argv[1]
    senha = os.environ.get("PUCEAD_SENHA") or sys.argv[2]
    tmp = os.environ.get("SCRATCHPAD", ".") + "/ead_test"
    client = EadClient(matricula=matricula, senha=senha, default_download_dir=tmp)
    try:
        await client.login()
        print(f"[ok] login. sesskey ...{client._sesskey[-4:]}")

        courses = await client.list_courses("inprogress")
        print(f"[ok] {len(courses)} cursos em andamento")

        state = await client.get_course_state(MAT1320_ID)
        sections = {s.id: s.title for s in state.sections}
        provas = [cm for cm in state.modules
                  if cm.module == "resource" and matches(cm.name, sections.get(cm.sectionid, ""), "prova")]
        print(f"[ok] {len(provas)} provas detectadas no MAT1320")
        for cm in provas[:5]:
            print(f"    - [{cm.id}] {cm.name}  (secao: {sections.get(cm.sectionid)})")

        if provas:
            f = await client.download_material(provas[0].id)
            print(f"[ok] baixado: {f.filename} ({f.size_bytes} bytes, {f.content_type})")
            print(f"      path: {f.path}")
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
