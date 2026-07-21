"""Site local de indicadores academicos (notas/faltas).

Uso: python site/app.py
Acesse http://localhost:5000 no proprio computador, ou http://<ip-da-maquina>:5000
de qualquer outro computador na mesma rede da escola.

Le a base em dados/consolidado.csv - rode scripts/consolidar.py de novo apos
cada coleta nova para atualizar os dados aqui mostrados.

ponytail: sem autenticacao - decisao explicita do usuario para o periodo de
testes (qualquer um na rede da escola ve dados de todos os alunos). Antes de
usar isso com a equipe/familias de verdade, adicionar login (ex: flask-login
com senha compartilhada, ou Basic Auth via um proxy na frente do Flask).
"""
import math
from pathlib import Path

import pandas as pd
from flask import Flask, abort, render_template, request

from indicadores import (
    alerta_descolamento,
    alunos_em_risco,
    apenas_matriculados,
    cruzamento_faltas_notas,
    evolucao_turma,
    evolucao_turma_por_disciplina,
    faltas_por_aluno_turma_ano,
    filtrar,
    media_geral_por_aluno_ano,
    medias_por_aluno_disciplina_ano,
    notas_detalhadas_aluno,
    resumo_anual_aluno,
    trajetoria_aluno,
    trajetoria_turma,
)

BASE_DIR = Path(__file__).parent
DADOS = BASE_DIR / "dados" / "consolidado.csv"

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


def carregar() -> pd.DataFrame:
    if not DADOS.exists():
        raise RuntimeError(f"{DADOS} nao existe - rode scripts/consolidar.py primeiro.")
    df = pd.read_csv(DADOS, encoding="utf-8-sig", dtype={"matricula": str}, low_memory=False)
    df["ano_letivo"] = pd.to_numeric(df["ano_letivo"], errors="coerce").astype("Int64")
    return df


def _limpo(v):
    """NaN/None -> None, para serializar em JSON sem quebrar o <script> da pagina."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(v, 2) if isinstance(v, float) else v


@app.route("/")
def index():
    # so alunos com dados no ano mais recente coletado (ver apenas_matriculados
    # - o filtro de Status do Gennera ja vem so com "Ativo" por padrao, entao
    # isso reflete quem realmente ainda esta matriculado, sem coleta extra).
    df = apenas_matriculados(carregar())
    curso_sel = request.args.get("curso", "")
    turma_sel = request.args.get("turma", "")
    disciplina_sel = request.args.get("disciplina", "")
    ano_sel = request.args.get("ano", "")

    segmentos = sorted(df["curso"].dropna().unique())
    # turma/disciplina so mostram o que existe no segmento escolhido, pra nao
    # listar "1ª Série" quando o filtro ja esta em Fundamental II, por exemplo.
    base_segmento = df[df["curso"] == curso_sel] if curso_sel else df
    turmas = sorted(base_segmento["turma"].dropna().unique())
    disciplinas = sorted(base_segmento["disciplina"].dropna().unique())
    anos_disponiveis = sorted(int(a) for a in df["ano_letivo"].dropna().unique())

    filtrado = filtrar(df, turma_sel, disciplina_sel, curso_sel)

    # medias e faltas: restringe as LINHAS ao ano escolhido antes de agregar,
    # entao a tabela vira uma unica coluna daquele ano (e alunos sem dados
    # naquele ano somem, em vez de aparecer com tudo vazio).
    filtrado_ano = filtrado[filtrado["ano_letivo"] == int(ano_sel)] if ano_sel else filtrado

    # so a media geral (todas as disciplinas juntas) aqui - o detalhe por
    # disciplina fica na pagina do proprio aluno, pra nao poluir a lista geral.
    medias = media_geral_por_aluno_ano(filtrado_ano)
    anos_medias = sorted(int(a) for a in medias.columns if a != "turma_atual")

    faltas = faltas_por_aluno_turma_ano(filtrado_ano)
    anos_faltas = sorted(int(a) for a in faltas.columns if a != "turma_atual")

    # risco/cruzamento precisa do ano anterior pra calcular a variacao, entao
    # calcula sobre TODOS os anos e so filtra o resultado (a variacao "que
    # terminou" no ano escolhido), nunca as linhas de entrada.
    cruzamento = cruzamento_faltas_notas(filtrado)
    if ano_sel:
        cruzamento = cruzamento[cruzamento["ano_letivo"] == int(ano_sel)]
    risco = alunos_em_risco(cruzamento).sort_values("delta_faltas", ascending=False)

    matriculas = df.drop_duplicates("aluno").set_index("aluno")["matricula"].to_dict()

    # item 4: com uma turma especifica filtrada, mostra a media DA TURMA por
    # disciplina/ano como referencia direta pra comparar com a tabela de
    # medias por aluno logo abaixo.
    media_turma_disciplina = None
    anos_media_turma = []
    if turma_sel:
        tabela_turma = evolucao_turma_por_disciplina(df, turma_sel)
        anos_media_turma = sorted(int(a) for a in tabela_turma.columns)
        media_turma_disciplina = tabela_turma.reset_index().to_dict("records")

    return render_template(
        "index.html",
        segmentos=segmentos,
        curso_sel=curso_sel,
        turmas=turmas,
        disciplinas=disciplinas,
        anos_disponiveis=anos_disponiveis,
        turma_sel=turma_sel,
        disciplina_sel=disciplina_sel,
        ano_sel=ano_sel,
        medias=medias.reset_index().to_dict("records"),
        anos_medias=anos_medias,
        faltas=faltas.reset_index().to_dict("records"),
        anos_faltas=anos_faltas,
        risco=risco.to_dict("records"),
        total_alunos=df["aluno"].nunique(),
        total_anos=anos_disponiveis,
        matriculas=matriculas,
        media_turma_disciplina=media_turma_disciplina,
        anos_media_turma=anos_media_turma,
    )


@app.route("/aluno/<matricula>")
def aluno(matricula):
    df = carregar()
    linhas_aluno = df[df["matricula"] == matricula]
    if linhas_aluno.empty:
        abort(404)
    nome = linhas_aluno["aluno"].iloc[0]

    resumo = resumo_anual_aluno(df, matricula)
    pontos, disciplinas_notas = trajetoria_aluno(df, matricula)
    alerta = alerta_descolamento(resumo)

    grafico = {
        "labels": [p["rotulo"] for p in pontos],
        "media_aluno": [_limpo(p["media_aluno"]) for p in pontos],
        "turma_media": [_limpo(p["turma_media"]) for p in pontos],
        "turma_sup": [
            _limpo(p["turma_media"] + p["turma_desvio"]) if pd.notna(p["turma_media"]) and pd.notna(p["turma_desvio"]) else None
            for p in pontos
        ],
        "turma_inf": [
            _limpo(p["turma_media"] - p["turma_desvio"]) if pd.notna(p["turma_media"]) and pd.notna(p["turma_desvio"]) else None
            for p in pontos
        ],
        "disciplinas": {d: [_limpo(v) for v in notas] for d, notas in disciplinas_notas.items()},
    }

    resumo_limpo = [{k: _limpo(v) for k, v in r.items()} for r in resumo]

    notas_linhas, instrumentos = notas_detalhadas_aluno(df, matricula)
    notas_linhas = [{k: _limpo(v) for k, v in linha.items()} for linha in notas_linhas]

    por_disciplina = medias_por_aluno_disciplina_ano(linhas_aluno).reset_index(level="aluno", drop=True)
    anos_disciplina = sorted(int(a) for a in por_disciplina.columns)
    disciplina_linhas = por_disciplina.reset_index().to_dict("records")

    return render_template(
        "aluno.html",
        nome=nome,
        matricula=matricula,
        resumo=resumo_limpo,
        alerta=alerta,
        grafico=grafico,
        notas_linhas=notas_linhas,
        instrumentos=instrumentos,
        disciplina_linhas=disciplina_linhas,
        anos_disciplina=anos_disciplina,
    )


@app.route("/turma/<nome>")
def turma_detalhe(nome):
    df = carregar()
    if nome not in df["turma"].unique():
        abort(404)

    resumo = evolucao_turma(df, nome)
    resumo_limpo = [{k: _limpo(v) for k, v in r.items()} for r in resumo]

    por_disciplina = evolucao_turma_por_disciplina(df, nome)
    anos_disciplina = sorted(int(a) for a in por_disciplina.columns)
    disciplina_linhas = por_disciplina.reset_index().to_dict("records")

    pontos, disciplinas_notas = trajetoria_turma(df, nome)
    grafico = {
        "labels": [p["rotulo"] for p in pontos],
        "media_turma": [_limpo(p["media_turma"]) for p in pontos],
        "disciplinas": {d: [_limpo(v) for v in notas] for d, notas in disciplinas_notas.items()},
    }

    return render_template(
        "turma.html",
        nome=nome,
        resumo=resumo_limpo,
        anos_disciplina=anos_disciplina,
        disciplina_linhas=disciplina_linhas,
        grafico=grafico,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
