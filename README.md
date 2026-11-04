# puc-ead-mcp

Servidor MCP que expõe o EAD da PUC-Rio (Moodle) como ferramentas pro Claude: listar matérias, mapear estrutura de curso, buscar e baixar slides/provas em bulk.

Testado em Windows + Claude Desktop + 5 matérias da graduação em CC (2026.2).

## O que resolve

Em vez de clicar em cada "Prova 1 (2024.1)", "Prova 1 (2024.2)" e baixar um a um, você pergunta no chat:

> baixa todas as provas de matemática discreta

E o Claude:
1. Chama `list_courses()` → encontra `MAT1320` (id 121330).
2. Chama `download_all_provas(121330)` → aplica heurística em `cm.name` e `section.title`, baixa todos os PDFs de prova/gabarito pra `downloads/curso_121330/prova/`.

## Instalação

```bash
git clone https://github.com/JoaoM06/puc-ead-mcp.git
cd puc-ead-mcp
pip install -e .
```

Requisitos: Python 3.11+.

## Configuração no Claude Desktop (Windows)

Edite `%APPDATA%\Claude\claude_desktop_config.json` e adicione o bloco `mcpServers` no topo:

```json
{
  "mcpServers": {
    "puc-ead": {
      "command": "C:\\Users\\SEU_USUARIO\\AppData\\Local\\Python\\pythoncore-3.14-64\\Scripts\\puc-ead-mcp.exe",
      "env": {
        "PUCEAD_MATRICULA": "SUA_MATRICULA",
        "PUCEAD_SENHA": "SUA_SENHA",
        "PUCEAD_DOWNLOAD_DIR": "C:\\Users\\SEU_USUARIO\\Downloads\\EAD"
      }
    }
  }
}
```

Dicas:
- Descobrir o path exato do `.exe`: `python -c "import sys, os; print(os.path.join(sys.prefix, 'Scripts', 'puc-ead-mcp.exe'))"`.
- Credenciais ficam em plaintext no arquivo — não compartilhe. Para endurecer, use `keyring` (ver "Segurança" abaixo).
- Depois de editar: **fechar o Claude Desktop pela bandeja** e reabrir. Reload da janela não basta.

### Usando com Claude Code ou outro cliente MCP

Qualquer cliente que fale MCP via stdio funciona. Exemplo pra Claude Code em `.claude/settings.json`:

```json
{
  "mcpServers": {
    "puc-ead": {
      "command": "puc-ead-mcp",
      "env": { "PUCEAD_MATRICULA": "...", "PUCEAD_SENHA": "..." }
    }
  }
}
```

## Tools expostas

| Tool | O que faz |
|---|---|
| `login(matricula, senha)` | Override manual (normalmente desnecessário — env vars autolog no startup). |
| `list_courses(classification='inprogress')` | Matérias do usuário. `classification`: `inprogress`\|`future`\|`past`\|`all`. |
| `get_course_structure(course_id)` | Árvore completa: seções + módulos (id, nome, tipo, url). |
| `search_materials(course_id, query='', kind=None, module_types=None)` | Busca com heurística. `kind`: `slide`\|`prova`\|`lista`\|`tarefa`. |
| `download_material(cm_id, dest_dir=None)` | Baixa um módulo `resource` individual. |
| `download_all_slides(course_id, dest_dir=None)` | Bulk de slides (heurística). |
| `download_all_provas(course_id, dest_dir=None)` | Bulk de provas + gabaritos. |
| `get_page_content(cm_id, as_text=True)` | Extrai conteúdo de `mod_page` (ex. aulas de INF1022). |

## Exemplos de uso

> lista minhas matérias ativas

> procura os slides da aula 3 de Sistemas Embarcados

> baixa todas as provas de matemática discreta

> me mostra o conteúdo da "Introdução - Aula 1" de Análise Léxica

## Como funciona

- Login via form POST em `/login/index.php` (CSRF `logintoken` extraído do HTML da página de login). reCAPTCHA v3 presente mas não bloqueia HTTP puro.
- Sessão mantida via cookie `MoodleSession`.
- Chamadas à API AJAX interna do Moodle (`/lib/ajax/service.php?sesskey=…&info=METHOD`), que os próprios widgets da UI usam. Principais:
  - `core_course_get_enrolled_courses_by_timeline_classification` → lista cursos.
  - `core_courseformat_get_state` → árvore do curso (seções + course modules).
- Download de `resource`: `GET /mod/resource/view.php?id=X` segue o redirect automático pra `/pluginfile.php/…/arquivo.pdf`. Se vier HTML (embed), parseia o link direto.
- A **Mobile Web Services API** pública (`/webservice/rest/server.php`) parece **desabilitada** nessa instalação → por isso usamos a API AJAX com cookie.

Mapa completo em [docs/api-map.md](docs/api-map.md).

## Heurísticas slide/prova

Regex em `cm.name` e `section.title` (prioridade: prova > slide > lista > tarefa):

| Kind | Regex |
|---|---|
| `prova` | `\b(prova\|p[12]\b\|exame\|avaliação\|gabarito\|final)\b` |
| `slide` | `\b(slide\|slides\|aula\s*\d+\|capítulo\s*\d+\|lecture)\b` |
| `lista` | `\b(lista\|exercícios?\|ficha\|homework\|hw\d*)\b` |
| `tarefa` | `\b(trabalho\|projeto\|entrega\|tarefa\|assignment)\b` |

Over-inclusive por design — melhor baixar um extra do que perder uma prova. Cada professor nomeia diferente (ex. INF1350 usa prefixo "Slides: 00 - ..."; MAT1320 tem "Prova I", "Prova 1 (2024.1)"; INF1022 usa `mod_page`), e as regex cobrem os padrões observados.

## Segurança

Credenciais em plaintext no `claude_desktop_config.json`. Aceitável para single-user/máquina pessoal, mas:
- Qualquer coisa que leia `%APPDATA%\Claude\` vê a senha.
- Backup `.bak-*` do config também — apague se não precisar.

Pra endurecer, adapte `client.py` pra ler do Windows Credential Manager via `keyring`:

```python
import keyring
self.senha = senha or keyring.get_password("puc-ead", self.matricula)
```

## Troubleshooting

**Não aparece no Claude Desktop:**
- Fechou da bandeja/dock e reabriu? (Reload da janela não basta.)
- Confira o path exato do `.exe` no config.
- Logs em `%APPDATA%\Claude\logs\` — procure por "puc-ead".

**Login falha:**
- Teste direto: `python scripts/test_login.py SUA_MATRICULA SUA_SENHA`.
- Se bloquear por reCAPTCHA (nunca aconteceu em testes), abra issue.

**Arquivo não baixa:**
- `cm.module` precisa ser `resource`. `assign`/`url`/`page` têm fluxos diferentes (use `get_page_content` pra `page`).

## Dev

```
src/puc_ead_mcp/
├── client.py       # EadClient (auth + ajax + download)
├── heuristics.py   # classificação slide/prova/lista/tarefa
├── models.py       # dataclasses: Course, Section, CourseModule, CourseState
├── server.py       # MCPServer + tools
└── __main__.py     # entry

scripts/
├── test_login.py   # smoke test: login HTTP puro
└── e2e.py          # e2e: login + lista + busca + download

docs/api-map.md     # mapa dos endpoints do Moodle usados
```

Smoke test:
```bash
python scripts/test_login.py $PUCEAD_MATRICULA $PUCEAD_SENHA
python scripts/e2e.py $PUCEAD_MATRICULA $PUCEAD_SENHA
```

## Licença

Uso pessoal. Não compartilhe materiais baixados protegidos por direito autoral do docente/universidade.
