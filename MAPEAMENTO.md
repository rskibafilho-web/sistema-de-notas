# MAPEAMENTO — Extração Gennera (notas e faltas)

Reconhecimento feito em 16/07/2026 na sessão autenticada de um usuário autorizado,
instituição **Colégio Global - EF2/EM** (`idInstitution=800`).

> ⚠️ **Confirme este documento antes da Etapa 3.** Os pontos marcados com ❓ são
> decisões suas ou coisas que eu não validei 100%.

---

## 1. Arquitetura do sistema

- SPA Angular. Módulos vivem em **subdomínios separados** com a mesma sessão:
  - `apps.gennera.com.br` — menu principal (`/admin/#/products2`)
  - `reports.gennera.com.br` — **área de Relatórios (é aqui que tudo acontece)**
  - `persons.` / `enrollment.` — cadastros (não usados aqui)
- Autenticação por **cookie de sessão** (login via `apps...#/login`). O script vai
  logar uma vez com Playwright e reusar o contexto para chamar as telas de relatório.

### Fluxo real de login (validado na Etapa 3, com Playwright headless)

Bem mais complexo do que um form usuário+senha simples:

1. **Email primeiro**: campo `#login-email` + botão "Próximo".
2. **Seleção de instituição** (só aparece se o email estiver vinculado a mais de
   uma instituição no Gennera): radios `input[name="institution"]`, escolher pelo
   texto do `<label>` (ex.: "Colégio Global") + "Próximo" de novo.
3. **Senha**: só then o campo `#login-password` fica visível + botão "Entrar".
4. **Handoff SSO por subdomínio**: a primeira vez que se navega para
   `reports.gennera.com.br` numa sessão nova, aparece uma tela intermediária
   ("Acesse sua conta" + botão "Continuar") antes de completar a autenticação
   nesse subdomínio — mesmo já logado em `apps.gennera.com.br`.
- `page.wait_for_load_state('networkidle')` não é confiável para detectar "login
  concluído" — o app tem tráfego de fundo contínuo (notificações) que nunca fica
  ocioso. Usar espera fixa + checar a URL.

## 2. Onde ficam os relatórios

Tela: `https://reports.gennera.com.br/#/institutions/800/reports`
Filtráveis por **Fonte de Dados**, **Categoria** (Financeiro, Diário de Classe,
Acadêmico, Gerencial, Notas) e descrição.

### Relatórios candidatos identificados

| Relatório | ID | Fonte | O que traz |
|---|---|---|---|
| **Espelho de Notas/Faltas** | `22151` | Matrícula | **notas + faltas juntas** por aluno/período/disciplina (nota por exame, Média do Período, Situação, Total de Faltas) |
| **Relatório de Faltas** | `17951` | Matrícula | faltas por aluno/disciplina/trimestre + Total (validado, ver §4) |
| Espelho de Notas | ❓ | Disciplina | notas por disciplina |
| Boletim Trimestral | ❓ | Matrícula | boletim padrão (notas) |
| Ata de Média Final | ❓ | Turma | médias finais da turma |

**Recomendação:** usar **Espelho de Notas/Faltas (`22151`)** como fonte principal —
sozinho já entrega nota **e** falta por aluno/disciplina/período, que é exatamente o
que a Etapa 4 precisa para o cruzamento. Manter **Relatório de Faltas (`17951`)** como
reforço se o detalhamento de faltas do 22151 não bastar.
❓ Confirmar se você concorda, ou se prefere Boletim/Espelho de Notas para as notas.

## 3. Filtros da tela de emissão (cascata **dependente**)

Botão **Filtros** → painel com, nesta ordem:

1. **Calendário Acadêmico** (= ano letivo) — obrigatório, dispara o resto
2. **Curso** → **Currículo** → **Módulo** → **Turma** (cada um só carrega depois do anterior)
3. **Status** (Ativo / Cancelado / Aberto / Reservado / Encerrado)
4. **Matrícula** (aluno específico, opcional)
5. **Período** (1º / 2º / 3º Trimestre, Exame Final, Recuperação 1º/2º/3º…)
6. Botão **Renderizar**

### IDs de Calendário Acadêmico (ano letivo) já capturados

| Ano | `idAcademicCalendar` |
|---|---|
| 2027 | 10700 |
| 2026 | 9738 |
| 2025 | 8690 |
| 2024 | 7352 |
| 2023.1 | 6270 |
| 2022.1 | 7096 |
| 2021.1 | 6544 |

Cursos em 2024: **Ensino Fundamental II**, **Ensino Médio**.

## 4. Formato de saída / exportação — **PONTO IMPORTANTE**

- Estes relatórios (Espelho, Faltas, Boletim) são **relatórios-documento**: renderizam
  em **HTML** na tela e exportam via botão **Imprimir → PDF**.
  **Não há botão nativo de Excel/CSV** nesses relatórios. ❓ Se você conhece um
  "Modelo de Exportação" específico que gera Excel, me diga o nome — não varri essa fonte.
- Renderizar **o ano inteiro sem filtrar turma levou 53 s** e gerou uma página gigante
  (todos os alunos). → **O script vai filtrar por turma**, o que também é necessário pela
  cascata de filtros e deixa cada emissão rápida.

### Método de coleta escolhido (Etapa 3)

**Raspar a tabela HTML renderizada** (não PDF, não engenharia reversa de API):
Playwright seleciona ano → curso → … → turma → período, clica **Renderizar**, espera, e
lê os blocos de aluno direto do DOM. Robusto e independente de mudanças internas da API.

Por trás, a tela usa `POST /institutions/800/reports/{id}/render?engine=reports` e
endpoints de filtro `GET /institutions/800/filters?resource=...` (academicCalendars,
coursesByCalendar, periods, …). Ficam documentados como plano B, caso o HTML se mostre
instável.

### Duas pegadinhas descobertas testando o script real (Etapa 3)

1. **O link do relatório abre em aba nova** (`target="_blank"` no `<a>` da lista de
   relatórios). Um clique normal do Playwright "funciona" sem erro nenhum, mas a
   navegação acontece numa aba que ninguém está observando — parecia que o clique
   simplesmente não fazia nada. Precisa `page.expect_popup()` ao redor do clique e
   trabalhar com a página retornada.
2. **Corrida na espera do "Renderizando"**: checar só "o texto 'Renderizando' sumiu"
   é ambíguo com "o render nem começou ainda" — em teste real isso causava extração
   de 0 linhas em menos de 1 segundo (o clique disparava, a checagem via que o texto
   ainda não tinha aparecido no DOM, e já dava como concluído). Preciso esperar o
   texto **aparecer** primeiro, só depois esperar ele sumir.

## 5. Estrutura dos dados (validada no Relatório de Faltas 17951)

Um **bloco por aluno**:

```
Cabeçalho: Nome | Curso | Matrícula | Série | Ano Letivo | Turma | Data de Emissão
Tabela:    Disciplina | 1º Trim (Faltas) | 2º Trim | 3º Trim | Total de Faltas (TF)
           Arte, Ciências, Ed. Física, Filosofia, Geografia, História,
           Inglês, Matemática, Português, ...
```

→ Linha final da base de faltas: `ano, curso, serie, turma, matricula, aluno, disciplina, periodo, faltas`.

### Confirmado ao vivo: Espelho de Notas/Faltas (22151)

Renderizado com dados reais (nomes/matrícula anonimizados no exemplo abaixo, 6º Ano, 2024, 1º Trimestre):

```
Aluno: Aluno Exemplo   Matrícula: 00000000
Curso: Ensino Fundamental II   Ano: 2024
Período: 1º Trimestre   Série / Turma: 6º Ano - 6º Ano

Disciplinas | PRV1 | PRV2 | TRAB1 | TRAB2 | TRAB3 | TRAB4 | TRAB5 | REC1 | REC2 | EXM | Média do Período | Situação | Total de Faltas
Matemática  | 7.90 | 5.80 | 9.00  |       |       |       |       |      |      |     | 7.40             | APR      | 0
Português   | 9.70 | 9.90 | 9.40  | 7.50  | 5.00  | 10.00 | 10.00 |      |      |     | 9.30             | APR      | 0
```

- Colunas de instrumento de avaliação (**PRV1/PRV2/TRAB1-5/REC1/REC2/EXM**) variam
  conforme o que a disciplina/período usa — nem toda coluna vem preenchida; o script
  deve tratar célula vazia como "não aplicável", não como zero.
- Notas em formato decimal com ponto (`"7.90"`), como string.
- `Situação` traz valores tipo `APR` (aprovado) — mapear os demais quando aparecerem
  (reprovado, recuperação etc.) durante a coleta real.
- **Total de Faltas** já vem por disciplina dentro do mesmo bloco — não precisa do
  Relatório de Faltas (17951) separado; o 22151 sozinho basta (conforme decidido).

### ⚠️ Achado crítico de performance

Renderizar o **22151 para o ano inteiro sem filtrar turma travou a aba por ~2 minutos**
e gerou **2557 tabelas HTML na página** (bem mais pesado que o 17951, que levou 53s).
Esse relatório é mais caro porque expande nota por instrumento de avaliação × disciplina
× período × aluno.

**Implicação direta para a Etapa 3:** o script **precisa sempre filtrar por
Curso → Currículo → Módulo → Turma** antes de Renderizar — nunca disparar com
apenas o ano selecionado, sob risco de travar/estourar timeout. A cascata de
turma não é só um filtro de conveniência aqui, é obrigatória por performance.

---

## Decisões confirmadas (16/07/2026)

1. **Fonte única de notas + faltas:** Espelho de Notas/Faltas (`22151`).
2. **Anos a coletar:** 2022 a 2026.

   | Ano | `idAcademicCalendar` |
   |---|---|
   | 2022.1 | 7096 |
   | 2023.1 | 6270 |
   | 2024 | 7352 |
   | 2025 | 8690 |
   | 2026 | 9738 |

   ❓ Nota: existem dois calendários de 2022/2023 (`2022.1`=7096, `2023.1`=6270) —
   os nomes sugerem calendário "ano.semestre"; vou usar esses IDs tais como aparecem
   no dropdown. Se sua instituição também tiver um "2023" sem ".1", me avise.
3. **Turmas:** todas, descobertas automaticamente por Curso → Currículo → Módulo →
   Turma para cada ano (script varre a cascata em vez de lista manual).
4. Export Excel/CSV nativo: não existe nesses relatórios — script vai raspar o HTML
   renderizado (ver §4).
