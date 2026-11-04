# PUC-Rio EAD — Mapa de API

Levantado em 2026-11-04 via navegador autenticado.

## Stack

- Base URL: `https://ead.puc-rio.br`
- Plataforma: **Moodle** (release 5.02 inferido do path `/public/...` e docs link `/502/`)
- Tema: PUC custom (`body.ead-puc-rio-br`)
- Login: form clássico com CSRF `logintoken` + reCAPTCHA v3 invisível (score-based; não bloqueou login programático via browser)
- Auth: cookie de sessão (`MoodleSession*`)
- API pública (REST webservice `/webservice/rest/server.php`): parece **não habilitada** para esta instalação — `/login/token.php?service=moodle_mobile_app` retorna `invalidlogin` mesmo com credenciais válidas.
- API interna (AJAX): `/lib/ajax/service.php?sesskey=XXX&info=METHODNAME` com body `[{index:0, methodname, args}]` — **funciona com cookie de sessão**. Esta é a abordagem.

## Login

1. `GET /loginccead/` → extrair `input[name=logintoken]` do HTML.
2. `POST /login/index.php` com `username`, `password`, `logintoken`. Content-Type form-urlencoded.
3. Sucesso → redirect pra `/my/`. Cookie `MoodleSession*` setado.
4. `sesskey` obtida do HTML de qualquer página autenticada: `<input name="sesskey" value="XXX">` ou via regex em `M.cfg = {... sesskey:"XXX" ...}`.

## Endpoints usados

### `core_course_get_enrolled_courses_by_timeline_classification`
Lista cursos do usuário. Args:
```json
{ "classification": "inprogress", "limit": 0, "offset": 0, "sort": "fullname" }
```
Classificações: `inprogress`, `future`, `past`, `all`.
Resposta: `{ courses: [{id, shortname, fullname, viewurl, startdate, enddate, ...}], nextoffset }`.

### `core_courseformat_get_state`
Retorna a árvore completa do curso. Args: `{ courseid: N }`.
Resposta `data` vem como **string JSON** (precisa de `JSON.parse`):
```
{
  course: { id, numsections, sectionlist: [sectionid...], baseurl, ... },
  section: [{ id, number, title, cmlist: [cmid...], visible, sectionurl, ... }],
  cm: [{ id, name, modname, module, url, sectionid, visible, uservisible, ... }]
}
```
Campo-chave: `module` (slug técnico) — valores observados: `resource`, `page`, `url`, `assign`, `forum`, `folder`, `subsection`, `label`, `zoom`.

## Download de material

Dado um `cm` do tipo `resource`:
- `GET cm.url` (ex: `/mod/resource/view.php?id=1451977`) → segue redirect automático pra `/pluginfile.php/CTXID/mod_resource/content/REV/filename.ext`.
- Content-Type real do arquivo (ex: `application/pdf`).
- Nome do arquivo: extrair do `Content-Disposition` ou do último segmento do URL final (decodificar `%20`).

Dado um `cm` do tipo `page`:
- `GET cm.url` (`/mod/page/view.php?id=X`) → HTML com conteúdo renderizado dentro de `#region-main .no-overflow` (seletor padrão Moodle). Pode conter links `pluginfile.php` embarcados.

Dado um `cm` do tipo `folder`:
- Página HTML lista os arquivos; parse de `a[href*="pluginfile.php"]`.
- Alternativamente: forçar download de todos via `?download_folder=1`.

Dado `url`: redirect pra site externo — só serve o `url` em si (sem download).

## Taxonomia dos cursos observados (2026.2)

| CourseId | Shortname | Módulos dominantes |
|---|---|---|
| 121048 | INF1018 | 51 assign, 23 url, 6 resource — não publica slides/provas |
| 118701 | INF1022 | 60 page, 30 resource — seções "Conteúdo P1/P2", "Slides de aula" |
| 118730 | INF1040 | 11 resource, seção "Slides Aulas" |
| 118744 | INF1350 | 12 resource (prefixo "Slides:"), seção "Introdução", "Arduino"... |
| 121330 | MAT1320 | 92 resource, 17 PDFs "Prova*", seções "Prova I com Gabarito", "Prova antiga" |

Sem Moodle `quiz` em nenhum curso. "Provas" = PDFs (resources) com naming/seção convencional por professor.

## Heurísticas de identificação

- **Slides**: `cm.name` começa com `/^Slides?:/i` ou `/aula\s*\d+/i` ou está em seção cujo título bate `/slide/i`.
- **Provas**: `cm.name` bate `/prova|p[12]\b|exame|avalia[çc][ãa]o/i` ou está em seção cujo título bate o mesmo regex.
- **Listas/exercícios**: `/lista|exerc[íi]cio|ficha/i`.

## Pegadinhas

- reCAPTCHA v3 no login — não bloqueou via browser real, mas pode bloquear request headless. Plano B: aceitar sessão/cookie fornecida pelo usuário via env var.
- `mod/resource` às vezes abre embed em vez de redirect direto; se status 200 e `content-type: text/html`, parsear `<a>` com `pluginfile.php`.
- Encoding: nomes de arquivos em `url-encoded UTF-8`; decodificar.
- `sesskey` expira com a sessão; recarregar do HTML se der 403.
