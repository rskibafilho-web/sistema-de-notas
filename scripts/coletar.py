"""Coleta notas/faltas do Gennera (relatorio Espelho de Notas/Faltas, id 22151).

Uso:
    python scripts/coletar.py --anos 2024,2025
    python scripts/coletar.py --anos 2024 --turmas "6º Ano" --headless
    python scripts/coletar.py --anos 2022,2023,2024,2025,2026 --force

Para cada ano letivo, descobre todas as turmas automaticamente (Curso -> Curriculo
-> Modulo -> Turma) e renderiza o relatorio turma por turma, salvando um CSV em
dados_exportados/{ano}/{turma}.csv. Reexecucoes pulam turmas ja coletadas, a
menos que --force seja passado.
"""
import argparse
import logging
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import Locator, Page, TimeoutError as PWTimeout, sync_playwright

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
SAIDA_DIR = BASE_DIR / "dados_exportados"
ERROS_LOG = BASE_DIR / "dados_exportados" / "erros_coleta.log"

URL_LOGIN = os.getenv("GENNERA_URL_LOGIN", "https://apps.gennera.com.br/public/#/login")
ID_INSTITUICAO = os.getenv("GENNERA_ID_INSTITUICAO", "800")
ID_RELATORIO = "22151"  # Espelho de Notas/Faltas

# idAcademicCalendar por ano, capturados no reconhecimento (ver MAPEAMENTO.md).
# ponytail: mapa fixo em vez de descobrir via API a cada run - IDs nao mudam
# de um ano ja fechado; se um ano novo aparecer, adicionar aqui.
ANOS_CALENDARIO = {
    "2021": "6544",
    "2022": "7096",
    "2023": "6270",
    "2024": "7352",
    "2025": "8690",
    "2026": "9738",
    "2027": "10700",
}

TIMEOUT_PADRAO = 30_000
TIMEOUT_RENDER = 90_000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coleta")


def slugify(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^\w\s-]", "", texto).strip().lower()
    return re.sub(r"[\s_-]+", "_", texto) or "turma"


def visivel(page: Page, seletor: str) -> Locator:
    """Playwright ja filtra :visible corretamente; usamos o proprio engine dele
    em vez de reimplementar (o app tem varias copias ocultas do mesmo formulario
    no DOM - confirmado no reconhecimento)."""
    return page.locator(f"{seletor}:visible")


def login(page: Page) -> None:
    """Login do Gennera e em duas ou tres etapas (como Google): email + 'Proximo';
    se o email estiver vinculado a mais de uma instituicao, uma tela extra pede
    para escolher (radios name=institution) + 'Proximo' de novo; so entao o
    campo de senha fica visivel + 'Entrar'. Confirmado inspecionando a tela
    real (ver #login-email / #login-password / MAPEAMENTO.md)."""
    try:
        usuario = os.environ["GENNERA_USUARIO"]
        senha = os.environ["GENNERA_SENHA"]
    except KeyError as exc:
        raise RuntimeError(
            f"Variavel {exc.args[0]} nao encontrada. Copie .env.example para .env "
            "e preencha usuario/senha antes de rodar a coleta."
        ) from exc
    nome_instituicao = os.getenv("GENNERA_INSTITUICAO_NOME", "Colégio Global")

    log.info("Fazendo login em %s", URL_LOGIN)
    page.goto(URL_LOGIN)

    email_input = visivel(page, "#login-email")
    email_input.wait_for(timeout=TIMEOUT_PADRAO)
    email_input.fill(usuario)
    visivel(page, "button:has-text('Próximo')").first.click()

    page.wait_for_timeout(1500)
    radios_instituicao = visivel(page, 'input[type=radio][name="institution"]')
    if radios_instituicao.count():
        log.info("Selecionando instituicao '%s'", nome_instituicao)
        rotulo = page.locator("label", has_text=nome_instituicao).first
        rotulo.wait_for(timeout=TIMEOUT_PADRAO)
        rotulo.click()
        visivel(page, "button:has-text('Próximo')").first.click()

    senha_input = visivel(page, "#login-password")
    senha_input.wait_for(timeout=TIMEOUT_PADRAO)
    senha_input.fill(senha)
    visivel(page, "button:has-text('Entrar')").first.click()

    # sem wait_for_load_state('networkidle') aqui: o app tem trafego de fundo
    # continuo (notificacoes etc) que nunca fica "idle", entao esse wait so
    # estoura por timeout mesmo com login ja bem-sucedido.
    page.wait_for_timeout(4000)
    if "login" in page.url.lower():
        raise RuntimeError("Login parece ter falhado - ainda na tela de login apos submissao")
    log.info("Login OK")


def abrir_relatorio(page_login: Page) -> Page:
    """Abre a tela de emissao do relatorio e retorna a PAGINA NOVA.

    O link do relatorio tem target="_blank" - o clique abre uma aba nova en
    vez de navegar a atual (confirmado inspecionando o DOM real: o click do
    Playwright "funcionava" sem erro mas nunca navegava, porque a navegacao
    acontecia numa aba que ninguem estava observando). Cada chamada retorna
    uma aba nova; a chamadora e responsavel por fechar a anterior.
    """
    url_lista = f"https://reports.gennera.com.br/#/institutions/{ID_INSTITUICAO}/reports"
    page_login.goto(url_lista)
    page_login.wait_for_timeout(2000)
    if "login" in page_login.url.lower():
        # primeira vez na sessao que acessa o subdominio reports.gennera.com.br:
        # aparece uma tela de handoff SSO pedindo para confirmar antes de
        # completar o redirecionamento (confirmado em teste real).
        log.info("Confirmando handoff SSO para reports.gennera.com.br")
        visivel(page_login, "button:has-text('Continuar')").first.click()
        page_login.wait_for_timeout(3000)

    seletor_link = f'a[href*="/reports/{ID_RELATORIO}/print"]'
    page_login.wait_for_selector(seletor_link, timeout=TIMEOUT_PADRAO)
    with page_login.expect_popup(timeout=TIMEOUT_PADRAO) as popup_info:
        visivel(page_login, seletor_link).first.click()
    page = popup_info.value
    page.wait_for_load_state()

    botao_filtros = visivel(page, "button:has-text('Filtros')")
    botao_filtros.first.wait_for(timeout=TIMEOUT_PADRAO)
    botao_filtros.first.click()
    page.wait_for_selector('select[ng-model="filter.idAcademicCalendar"]:visible', timeout=TIMEOUT_PADRAO)
    return page


def selecionar_ano(page: Page, id_calendario: str) -> None:
    select = visivel(page, 'select[ng-model="filter.idAcademicCalendar"]').first
    select.select_option(value=f"number:{id_calendario}")
    page.wait_for_timeout(1200)


def clicar_link_cascata(page: Page, funcao: str, campo: str) -> None:
    seletor = f"a[ng-click*=\"{funcao}('{campo}')\"]"
    link = visivel(page, seletor)
    if link.count() == 0:
        return
    link.first.click()
    page.wait_for_timeout(1200)


def selecionar_todas_periodos(page: Page) -> None:
    link = visivel(page, "a[ng-click*='selectAll(filters.periods)']")
    if link.count():
        link.first.click()


def carregar_todas_turmas(page: Page) -> None:
    """Marca 'selecionar tudo' em curso/curriculo/modulo para que a lista de
    turmas (filters.classes) venha completa - e a partir dela que iteramos."""
    clicar_link_cascata(page, "selectAllEnrollmentFilters", "courses")
    clicar_link_cascata(page, "selectAllEnrollmentFilters", "curriculums")
    clicar_link_cascata(page, "selectAllEnrollmentFilters", "modules")
    page.wait_for_timeout(1500)


def listar_turmas(page: Page) -> list[dict]:
    """Retorna lista de {grupo, nome} respeitando a ordem do DOM (mesma ordem
    usada depois para marcar o checkbox correspondente por indice)."""
    turmas = page.evaluate(
        """() => {
            const checkboxes = Array.from(document.querySelectorAll('input[ng-model="class.enabled"]'))
                .filter(el => el.offsetParent !== null);
            return checkboxes.map(cb => {
                const label = cb.closest('label');
                const nome = label ? label.innerText.trim() : '';
                const grupoNode = cb.closest('div[ng-repeat*="group.id"]');
                const header = grupoNode ? grupoNode.querySelector(':scope > div:not([ng-repeat])') : null;
                return {grupo: header ? header.innerText.trim() : '', nome: nome};
            });
        }"""
    )
    return turmas


def selecionar_turma_unica(page: Page, indice: int) -> None:
    desmarcar = visivel(page, "a[ng-click*=\"unselectAllEnrollmentFilters('classes')\"]")
    if desmarcar.count():
        desmarcar.first.click()
        page.wait_for_timeout(400)
    # mesma lista/ordem de listar_turmas: so os checkboxes visiveis contam,
    # o app mantem copias ocultas do formulario no DOM (ver MAPEAMENTO.md).
    checkboxes = visivel(page, 'input[ng-model="class.enabled"]')
    checkboxes.nth(indice).check(force=True)
    page.wait_for_timeout(400)


def renderizar(page: Page) -> bool:
    botao = visivel(page, 'button[ng-click="renderReport(report, filter)"]').first
    botao.click()
    # wait_for_function avalia a condicao IMEDIATAMENTE antes de sondar; se so
    # esperassemos o "Renderizando" sumir, um clique cujo digest do Angular
    # ainda nao inseriu esse texto no DOM faria a espera "passar" antes do
    # render sequer comecar (confirmado: causava extracao de 0 linhas em <1s).
    # Por isso esperamos ele aparecer primeiro.
    try:
        page.wait_for_function(
            "() => document.body.innerText.includes('Renderizando')",
            timeout=5_000,
        )
    except PWTimeout:
        pass  # pode ter renderizado rapido demais pro estado intermediario aparecer
    try:
        page.wait_for_function(
            "() => !document.body.innerText.includes('Renderizando')",
            timeout=TIMEOUT_RENDER,
        )
        return True
    except PWTimeout:
        return False


def extrair_blocos_brutos(page: Page) -> list[dict]:
    """Le os blocos aluno x periodo direto do DOM renderizado, sem alinhar
    colunas ainda (isso fica em `montar_linha`, testavel sem navegador).

    Estrutura confirmada no template do relatorio (ver MAPEAMENTO.md secao 5):
    cada bloco e um <div style="page-break-before:always"> com duas tabelas:
    a primeira com Aluno/Matricula/Curso/Ano/Periodo/Turma, a segunda com as
    disciplinas e colunas de instrumento de avaliacao (variam por periodo).
    """
    return page.evaluate(
        r"""() => {
            const blocos = Array.from(document.querySelectorAll('div[style*="page-break-before"]'));
            const resultado = [];
            for (const bloco of blocos) {
                const tabelas = bloco.querySelectorAll('table');
                if (tabelas.length < 2) continue;
                const infoTds = Array.from(tabelas[0].querySelectorAll('td')).map(td => td.innerText.trim());
                const info = {};
                for (const txt of infoTds) {
                    const idx = txt.indexOf(':');
                    if (idx === -1) continue;
                    info[txt.slice(0, idx).trim()] = txt.slice(idx + 1).trim();
                }
                const linhasTabela = Array.from(tabelas[1].querySelectorAll('tr'));
                if (!linhasTabela.length) continue;
                const headers = Array.from(linhasTabela[0].querySelectorAll('td,th')).map(c => c.innerText.trim());
                const linhas = [];
                for (let r = 1; r < linhasTabela.length; r++) {
                    const celulas = Array.from(linhasTabela[r].querySelectorAll('td,th')).map(c => c.innerText.trim());
                    if (celulas.length >= 2) linhas.push(celulas);
                }
                resultado.push({info, headers, linhas});
            }
            return resultado;
        }"""
    )


def montar_linha(info: dict, headers: list[str], celulas: list[str]) -> dict:
    """Alinha uma linha da tabela de disciplinas com os headers.

    A primeira celula costuma trazer um indice numerico sem header
    correspondente (headers[0] e sempre "Disciplinas", que ja vira a chave
    'disciplina'); o resto das celulas casa com headers[1:]. Essa distincao
    e o motivo do teste em test_coletar.py - a versao ingenua (mapear
    celulas[c] com headers[c]) desalinhava Situacao/Total de Faltas em uma
    coluna quando o indice numerico estava presente.
    """
    offset = 1 if celulas and celulas[0].isdigit() else 0
    linha = {
        "aluno": info.get("Aluno", ""),
        "matricula": info.get("Matrícula", ""),
        "curso": info.get("Curso", ""),
        "ano_letivo": info.get("Ano", ""),
        "periodo": info.get("Período", ""),
        "serie_turma": info.get("Série / Turma", ""),
        "disciplina": celulas[offset] if len(celulas) > offset else "",
    }
    resto = celulas[offset + 1:]
    for i, valor in enumerate(resto):
        nome_col = headers[i + 1] if i + 1 < len(headers) else f"col_{i + 1}"
        linha[nome_col] = valor
    return linha


def extrair_dados(page: Page) -> list[dict]:
    blocos = extrair_blocos_brutos(page)
    linhas = []
    for bloco in blocos:
        for celulas in bloco["linhas"]:
            linhas.append(montar_linha(bloco["info"], bloco["headers"], celulas))
    return linhas


def registrar_erro(mensagem: str) -> None:
    ERROS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ERROS_LOG, "a", encoding="utf-8") as f:
        f.write(mensagem + "\n")
    log.error(mensagem)


def reabrir_com_filtros(page_login: Page, id_calendario: str) -> Page:
    """Abre uma aba nova de relatorio (abrir_relatorio) e ja deixa a cascata
    de filtros pronta (ano + todos os periodos + todas as turmas carregadas)."""
    page = abrir_relatorio(page_login)
    selecionar_ano(page, id_calendario)
    selecionar_todas_periodos(page)
    carregar_todas_turmas(page)
    return page


def coletar_ano(page_login: Page, ano: str, filtro_turmas: list[str] | None, forcar: bool) -> None:
    id_calendario = ANOS_CALENDARIO.get(ano)
    if not id_calendario:
        registrar_erro(f"Ano {ano} sem idAcademicCalendar conhecido em ANOS_CALENDARIO - pulei.")
        return

    pasta_ano = SAIDA_DIR / ano
    pasta_ano.mkdir(parents=True, exist_ok=True)

    log.info("=== Ano %s (calendario %s) ===", ano, id_calendario)
    page = reabrir_com_filtros(page_login, id_calendario)

    turmas = listar_turmas(page)
    if not turmas:
        registrar_erro(f"Ano {ano}: nenhuma turma encontrada apos carregar cascata de filtros.")
        page.close()
        return
    log.info("Ano %s: %d turmas encontradas", ano, len(turmas))

    for i, turma in enumerate(turmas):
        nome_turma = turma["nome"] or f"turma_{i}"
        grupo = turma["grupo"] or ""
        if filtro_turmas and not any(f.lower() in nome_turma.lower() for f in filtro_turmas):
            continue

        slug = slugify(f"{grupo}_{nome_turma}")
        destino = pasta_ano / f"{slug}.csv"
        if destino.exists() and not forcar:
            log.info("[%s] %s ja coletada, pulando (use --force para refazer)", ano, slug)
            continue

        # o relatorio abre numa aba nova (target=_blank) e essa aba fica "gasta"
        # apos o render; refaz a cascata numa aba nova antes de cada turma
        # (exceto a primeira, que ja saiu pronta do setup acima do loop) - isso
        # roda incondicionalmente aqui em vez de "no fim do sucesso" para nao
        # deixar a proxima turma orfa de filtros quando esta falha ou vem vazia.
        if i > 0:
            page.close()
            page = reabrir_com_filtros(page_login, id_calendario)

        log.info("[%s] Renderizando turma %s / %s (%d/%d)", ano, grupo, nome_turma, i + 1, len(turmas))
        try:
            selecionar_turma_unica(page, i)
            ok = renderizar(page)
            if not ok:
                registrar_erro(f"Ano {ano}, turma '{grupo} / {nome_turma}': timeout ao renderizar, tentando 1x de novo.")
                ok = renderizar(page)
            if not ok:
                registrar_erro(f"Ano {ano}, turma '{grupo} / {nome_turma}': timeout persistente, pulei.")
                continue

            dados = extrair_dados(page)
            if not dados:
                log.warning("[%s] %s: renderizou sem nenhuma linha (turma sem matriculas ativas?)", ano, slug)
                continue

            pd.DataFrame(dados).to_csv(destino, index=False, encoding="utf-8-sig")
            log.info("[%s] %s: %d linhas salvas em %s", ano, slug, len(dados), destino.relative_to(BASE_DIR))
        except Exception as exc:  # noqa: BLE001 - continuar coleta mesmo se uma turma falhar
            registrar_erro(f"Ano {ano}, turma '{grupo} / {nome_turma}': erro inesperado: {exc!r}")
            continue

    page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anos", required=True, help="anos separados por virgula, ex: 2024,2025")
    parser.add_argument("--turmas", default=None, help="filtro opcional por substring do nome da turma, separado por virgula")
    parser.add_argument("--headless", action="store_true", help="roda sem abrir janela do navegador")
    parser.add_argument("--force", action="store_true", help="recoleta turmas mesmo se ja houver CSV salvo")
    args = parser.parse_args()

    anos = [a.strip() for a in args.anos.split(",") if a.strip()]
    filtro_turmas = [t.strip() for t in args.turmas.split(",")] if args.turmas else None

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=args.headless)
        page = navegador.new_page()
        try:
            login(page)
            for ano in anos:
                coletar_ano(page, ano, filtro_turmas, args.force)
        finally:
            navegador.close()

    if ERROS_LOG.exists():
        log.warning("Coleta concluida com erros - veja %s", ERROS_LOG)
    else:
        log.info("Coleta concluida sem erros.")


if __name__ == "__main__":
    main()
