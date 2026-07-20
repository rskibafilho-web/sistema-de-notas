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
    cruzamento_faltas_notas,
    faltas_por_aluno_turma_ano,
    filtrar,
    medias_por_aluno_disciplina_ano,
    resumo_anual_aluno,
    trajetoria_aluno,
)

BASE_DIR = Path(__file__).parent
DADOS = BASE_DIR / "dados" / "consolidado.csv"

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


def carregar() -> pd.DataFrame:
    if not DADOS.exists():
        raise RuntimeError(f"{DADOS} nao existe - rode scripts/consolidar.py primeiro.")
    df = pd.read_csv(DADOS, encoding="utf-8-sig", dtype={"matricula": str})
    df["ano_letivo"] = pd.to_numeric(df["ano_letivo"], errors="coerce").astype("Int64")
    return df


def _limpo(v):
    """NaN/None -> None, para serializar em JSON sem quebrar o <script> da pagina."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(v, 2) if isinstance(v, float) else v


@app.route("/")
def index():
    df = carregar()
    turma_sel = request.args.get("turma", "")
    disciplina_sel = request.args.get("disciplina", "")
    ano_sel = request.args.get("ano", "")

    turmas = sorted(df["turma"].dropna().unique())
    disciplinas = sorted(df["disciplina"].dropna().unique())
    anos_disponiveis = sorted(int(a) for a in df["ano_letivo"].dropna().unique())

    filtrado = filtrar(df, turma_sel, disciplina_sel)

    # medias e faltas: restringe as LINHAS ao ano escolhido antes de agregar,
    # entao a tabela vira uma unica coluna daquele ano (e alunos sem dados
    # naquele ano somem, em vez de aparecer com tudo vazio).
    filtrado_ano = filtrado[filtrado["ano_letivo"] == int(ano_sel)] if ano_sel else filtrado

    medias = medias_por_aluno_disciplina_ano(filtrado_ano)
    anos_medias = sorted(int(a) for a in medias.columns)

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

    return render_template(
        "index.html",
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

    return render_template(
        "aluno.html",
        nome=nome,
        matricula=matricula,
        resumo=resumo_limpo,
        alerta=alerta,
        grafico=grafico,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
