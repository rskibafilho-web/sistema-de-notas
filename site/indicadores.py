"""Calculo dos 3 indicadores pedidos, separado das rotas Flask para ser
testavel sem servidor (ver test_indicadores.py).
"""
import re

import pandas as pd

PERIODOS_REGULARES = {"1º Trimestre", "2º Trimestre", "3º Trimestre"}


def filtrar(df: pd.DataFrame, turma: str = "", disciplina: str = "", curso: str = "") -> pd.DataFrame:
    if curso:
        df = df[df["curso"] == curso]
    if turma:
        df = df[df["turma"] == turma]
    if disciplina:
        df = df[df["disciplina"] == disciplina]
    return df


def apenas_matriculados(df: pd.DataFrame) -> pd.DataFrame:
    """So mantem alunos cujo ultimo ano com dados e o ano mais recente
    coletado.

    O filtro de Status na tela de emissao do Gennera vem com so "Ativo"
    marcado por padrao (confirmado ao vivo - ver MAPEAMENTO.md), e o script
    de coleta nunca mexe nesse filtro. Ou seja, cada ano ja coletado so tem
    quem estava com matricula Ativa naquele ano - um aluno que nao aparece
    no ano mais recente genuinamente deixou de estar ativo (formou, saiu,
    transferiu), nao e uma falha de coleta.
    """
    if df.empty:
        return df
    ultimo_ano_geral = df["ano_letivo"].max()
    ultimo_ano_por_aluno = df.groupby("matricula")["ano_letivo"].transform("max")
    return df[ultimo_ano_por_aluno == ultimo_ano_geral]


def medias_por_aluno_disciplina_ano(df: pd.DataFrame) -> pd.DataFrame:
    """Media da nota por aluno/disciplina, uma coluna por ano letivo.

    So considera trimestres regulares (exclui Exame Final/Recuperacao, que
    inflam ou distorcem a media de quem passou direto).
    """
    regulares = df[df["periodo"].isin(PERIODOS_REGULARES)]
    return (
        regulares.groupby(["aluno", "disciplina", "ano_letivo"])["nota"]
        .mean()
        .reset_index()
        .pivot_table(index=["aluno", "disciplina"], columns="ano_letivo", values="nota")
    )


def media_geral_por_aluno_ano(df: pd.DataFrame) -> pd.DataFrame:
    """Media geral do aluno (todas as disciplinas juntas), uma coluna por ano
    letivo - visao resumida pra tela inicial (o detalhe por disciplina fica
    na pagina do proprio aluno, ver medias_por_aluno_disciplina_ano)."""
    regulares = df[df["periodo"].isin(PERIODOS_REGULARES)]
    ultima_turma = df.sort_values("ano_letivo").groupby("aluno")["turma"].last()
    medias = (
        regulares.groupby(["aluno", "ano_letivo"])["nota"]
        .mean()
        .reset_index()
        .pivot_table(index="aluno", columns="ano_letivo", values="nota")
    )
    medias.insert(0, "turma_atual", ultima_turma)
    return medias


def faltas_por_aluno_turma_ano(df: pd.DataFrame) -> pd.DataFrame:
    """Soma de faltas no ano por aluno, uma coluna por ano letivo.

    Agrupa so por aluno (nao por aluno+turma): a turma de um aluno muda todo
    ano (6o Ano -> 7o Ano -> ...), entao agrupar por turma tambem quebraria a
    evolucao em varias linhas separadas em vez de uma tendencia continua por
    aluno. A ultima turma conhecida entra so como coluna informativa.
    """
    ultima_turma = df.sort_values("ano_letivo").groupby("aluno")["turma"].last()
    faltas = (
        df.groupby(["aluno", "ano_letivo"])["faltas"]
        .sum()
        .reset_index()
        .pivot_table(index="aluno", columns="ano_letivo", values="faltas")
    )
    faltas.insert(0, "turma_atual", ultima_turma)
    return faltas


def cruzamento_faltas_notas(df: pd.DataFrame) -> pd.DataFrame:
    """Para cada aluno, variacao ano-a-ano de nota media e de faltas totais.

    Retorna uma linha por (aluno, ano) a partir do segundo ano com dados,
    com delta_nota e delta_faltas ja calculados.
    """
    regulares = df[df["periodo"].isin(PERIODOS_REGULARES)]
    nota_ano = regulares.groupby(["aluno", "ano_letivo"])["nota"].mean().reset_index()
    faltas_ano = df.groupby(["aluno", "ano_letivo"])["faltas"].sum().reset_index()
    base = nota_ano.merge(faltas_ano, on=["aluno", "ano_letivo"]).sort_values(["aluno", "ano_letivo"])
    base["delta_nota"] = base.groupby("aluno")["nota"].diff()
    base["delta_faltas"] = base.groupby("aluno")["faltas"].diff()
    return base.dropna(subset=["delta_nota", "delta_faltas"])


def alunos_em_risco(cruzamento: pd.DataFrame) -> pd.DataFrame:
    """Faltas subindo E nota caindo no mesmo intervalo - sinal de alerta."""
    return cruzamento[(cruzamento["delta_nota"] < 0) & (cruzamento["delta_faltas"] > 0)]


ORDEM_PERIODO = {"1º Trimestre": 1, "2º Trimestre": 2, "3º Trimestre": 3}


def _media_por_aluno_ano_turma(regulares: pd.DataFrame) -> pd.DataFrame:
    """Media anual de cada aluno (todas as disciplinas), com a turma daquele ano.
    Base para comparar um aluno especifico contra a distribuicao da turma."""
    return (
        regulares.groupby(["matricula", "aluno", "turma", "ano_letivo"])["nota"]
        .mean()
        .reset_index()
    )


def resumo_anual_aluno(df: pd.DataFrame, matricula: str) -> list[dict]:
    """Um card por ano: media do aluno, media/desvio da turma, z-score,
    percentil ('melhor que X% da turma') e faltas no ano.
    """
    regulares = df[df["periodo"].isin(PERIODOS_REGULARES)]
    medias_aluno_ano = _media_por_aluno_ano_turma(regulares)

    linhas = []
    anos = sorted(df[df["matricula"] == matricula]["ano_letivo"].dropna().unique())
    for ano in anos:
        turma_serie = df[(df["matricula"] == matricula) & (df["ano_letivo"] == ano)]["turma"]
        turma = turma_serie.iloc[0] if len(turma_serie) else None
        faltas = df[(df["matricula"] == matricula) & (df["ano_letivo"] == ano)]["faltas"].sum()

        turma_alunos = medias_aluno_ano[(medias_aluno_ano["turma"] == turma) & (medias_aluno_ano["ano_letivo"] == ano)]
        media_aluno_row = turma_alunos[turma_alunos["matricula"] == matricula]
        media_aluno = media_aluno_row["nota"].iloc[0] if len(media_aluno_row) else None

        turma_media = turma_alunos["nota"].mean()
        turma_desvio = turma_alunos["nota"].std()
        z = ((media_aluno - turma_media) / turma_desvio) if (media_aluno is not None and turma_desvio) else None
        percentil = (
            (turma_alunos["nota"] < media_aluno).mean() * 100
            if media_aluno is not None and len(turma_alunos) > 1
            else None
        )

        linhas.append({
            "ano_letivo": int(ano),
            "turma": turma,
            "media_aluno": media_aluno,
            "faltas": int(faltas),
            "turma_media": turma_media,
            "turma_desvio": turma_desvio,
            "z": z,
            "percentil": percentil,
        })
    return linhas


def trajetoria_aluno(df: pd.DataFrame, matricula: str) -> tuple[list[dict], dict]:
    """Serie (ano, periodo) com a media geral do aluno vs a faixa (media +-
    desvio) da turma naquele periodo, e um dict {disciplina: [notas...]} na
    mesma ordem dos pontos, para sobrepor no grafico.
    """
    regulares = df[df["periodo"].isin(PERIODOS_REGULARES)].copy()
    regulares["ordem_periodo"] = regulares["periodo"].map(ORDEM_PERIODO)

    aluno_df = regulares[regulares["matricula"] == matricula]
    pontos_chave = (
        aluno_df[["ano_letivo", "periodo", "ordem_periodo", "turma"]]
        .drop_duplicates()
        .sort_values(["ano_letivo", "ordem_periodo"])
    )

    medias_por_aluno_periodo = (
        regulares.groupby(["ano_letivo", "periodo", "turma", "matricula"])["nota"].mean().reset_index()
    )

    pontos = []
    disciplinas_aluno: dict[str, list] = {}
    todas_disciplinas = sorted(aluno_df["disciplina"].dropna().unique())
    for d in todas_disciplinas:
        disciplinas_aluno[d] = []

    for _, chave in pontos_chave.iterrows():
        contexto = medias_por_aluno_periodo[
            (medias_por_aluno_periodo["ano_letivo"] == chave["ano_letivo"])
            & (medias_por_aluno_periodo["periodo"] == chave["periodo"])
            & (medias_por_aluno_periodo["turma"] == chave["turma"])
        ]
        media_aluno_row = contexto[contexto["matricula"] == matricula]
        media_aluno = media_aluno_row["nota"].iloc[0] if len(media_aluno_row) else None

        pontos.append({
            "rotulo": f"{int(chave['ano_letivo'])} · {chave['periodo']}",
            "ano_letivo": int(chave["ano_letivo"]),
            "periodo": chave["periodo"],
            "media_aluno": media_aluno,
            "turma_media": contexto["nota"].mean(),
            "turma_desvio": contexto["nota"].std(),
        })

        notas_periodo = aluno_df[
            (aluno_df["ano_letivo"] == chave["ano_letivo"]) & (aluno_df["periodo"] == chave["periodo"])
        ]
        for d in todas_disciplinas:
            linha_d = notas_periodo[notas_periodo["disciplina"] == d]
            disciplinas_aluno[d].append(linha_d["nota"].iloc[0] if len(linha_d) else None)

    return pontos, disciplinas_aluno


def alerta_descolamento(resumo: list[dict]) -> str | None:
    """Se o z-score do aluno caiu de forma relevante do penultimo pro ultimo
    ano com dados, sinaliza para priorizar conversa com a familia."""
    com_dados = [r for r in resumo if r["media_aluno"] is not None and r["z"] is not None]
    if len(com_dados) < 2:
        return None
    anterior, atual = com_dados[-2], com_dados[-1]
    if atual["media_aluno"] < anterior["media_aluno"] and atual["z"] < anterior["z"] - 0.5:
        return "Média e posição na turma caíram — o aluno descolou dos colegas. Prioridade de conversa."
    return None


def evolucao_turma(df: pd.DataFrame, nome_turma: str) -> list[dict]:
    """Media geral da turma (todas as disciplinas) por ano letivo, com numero
    de alunos e media de faltas.

    Compara o mesmo NOME de turma (ex: "6o Ano - 6o Ano") entre anos - cada
    ano e uma turma de alunos diferente (a coorte avanca de serie), entao
    isso mostra a tendencia do nivel ao longo do tempo, nao de um grupo fixo
    de alunos (ver MAPEAMENTO.md - nao ha um id de coorte estavel nos dados).
    """
    turma_df = df[df["turma"] == nome_turma]
    regulares = turma_df[turma_df["periodo"].isin(PERIODOS_REGULARES)]

    linhas = []
    for ano in sorted(turma_df["ano_letivo"].dropna().unique()):
        ano_reg = regulares[regulares["ano_letivo"] == ano]
        media_por_aluno = ano_reg.groupby("matricula")["nota"].mean()
        faltas_por_aluno = turma_df[turma_df["ano_letivo"] == ano].groupby("matricula")["faltas"].sum()
        linhas.append({
            "ano_letivo": int(ano),
            "media_turma": media_por_aluno.mean() if len(media_por_aluno) else None,
            "desvio_turma": media_por_aluno.std() if len(media_por_aluno) else None,
            "num_alunos": int(media_por_aluno.shape[0]),
            "faltas_media": faltas_por_aluno.mean() if len(faltas_por_aluno) else None,
        })
    return linhas


def evolucao_turma_por_disciplina(df: pd.DataFrame, nome_turma: str) -> pd.DataFrame:
    """Media da turma por disciplina, uma coluna por ano letivo - usado na
    pagina da turma e como comparativo na tabela de medias por aluno quando
    uma turma especifica esta filtrada (item 4: turma vs aluno)."""
    turma_df = df[df["turma"] == nome_turma]
    regulares = turma_df[turma_df["periodo"].isin(PERIODOS_REGULARES)]
    return (
        regulares.groupby(["disciplina", "ano_letivo"])["nota"]
        .mean()
        .reset_index()
        .pivot_table(index="disciplina", columns="ano_letivo", values="nota")
    )


def trajetoria_turma(df: pd.DataFrame, nome_turma: str) -> tuple[list[dict], dict]:
    """Serie (ano, periodo) com a media geral da turma e por disciplina -
    mesmo padrao de trajetoria_aluno, sem banda de comparacao (aqui a turma
    e a propria referencia)."""
    turma_df = df[df["turma"] == nome_turma].copy()
    regulares = turma_df[turma_df["periodo"].isin(PERIODOS_REGULARES)].copy()
    regulares["ordem_periodo"] = regulares["periodo"].map(ORDEM_PERIODO)

    pontos_chave = (
        regulares[["ano_letivo", "periodo", "ordem_periodo"]]
        .drop_duplicates()
        .sort_values(["ano_letivo", "ordem_periodo"])
    )

    todas_disciplinas = sorted(regulares["disciplina"].dropna().unique())
    pontos = []
    disciplinas_turma: dict[str, list] = {d: [] for d in todas_disciplinas}

    for _, chave in pontos_chave.iterrows():
        contexto = regulares[
            (regulares["ano_letivo"] == chave["ano_letivo"]) & (regulares["periodo"] == chave["periodo"])
        ]
        media_por_aluno = contexto.groupby("matricula")["nota"].mean()
        pontos.append({
            "rotulo": f"{int(chave['ano_letivo'])} · {chave['periodo']}",
            "media_turma": media_por_aluno.mean() if len(media_por_aluno) else None,
        })
        for d in todas_disciplinas:
            nota_d = contexto[contexto["disciplina"] == d]["nota"].mean()
            disciplinas_turma[d].append(nota_d if pd.notna(nota_d) else None)

    return pontos, disciplinas_turma


# ordem dos segmentos (Fundamental antes de Medio) para a progressao escolar
_ORDEM_CURSO = {"fundamental": 0, "médio": 1, "medio": 1}


def _ordem_turma(nome: str, curso: str) -> tuple:
    """Chave de ordenacao na progressao escolar: 6º->9º Ano (Fund II), depois
    1ª->3ª Série (EM). Extrai o numero da serie do nome da turma e usa o
    segmento como criterio primario."""
    curso_l = (curso or "").lower()
    curso_rank = next((v for k, v in _ORDEM_CURSO.items() if k in curso_l), 9)
    m = re.match(r"\s*(\d+)", nome or "")
    serie = int(m.group(1)) if m else 99
    return (curso_rank, serie, nome or "")


def _quartis(valores: list) -> dict | None:
    """min / Q1 / mediana / Q3 / max de uma lista de notas, para a barra de
    quartis (box plot horizontal) no card da turma."""
    if not valores:
        return None
    s = pd.Series(valores)
    return {
        "min": float(s.min()),
        "q1": float(s.quantile(0.25)),
        "mediana": float(s.quantile(0.5)),
        "q3": float(s.quantile(0.75)),
        "max": float(s.max()),
    }


def _latest_e_tendencia(valores: dict, anos: list):
    """Ultima nota com dado + variacao pro ano anterior com dado. Ignora anos
    sem nota, entao a tendencia compara os dois anos reais mais recentes."""
    seq = [valores[a] for a in anos if pd.notna(valores.get(a))]
    if not seq:
        return None, None
    latest = seq[-1]
    trend = (seq[-1] - seq[-2]) if len(seq) >= 2 else None
    return latest, trend


def _risco_por_aluno(df: pd.DataFrame) -> dict:
    """{aluno: True} se a transicao MAIS RECENTE do aluno teve nota caindo e
    faltas subindo (mesmo criterio de alunos_em_risco, mas so a ultima)."""
    cruz = cruzamento_faltas_notas(df)
    risco = {}
    for aluno, grupo in cruz.sort_values("ano_letivo").groupby("aluno"):
        ultima = grupo.iloc[-1]
        risco[aluno] = bool(ultima["delta_nota"] < 0 and ultima["delta_faltas"] > 0)
    return risco


def dashboard_por_turma(df: pd.DataFrame) -> list[dict]:
    """Um card por turma (agrupado pela turma ATUAL do aluno), com media da
    turma, distribuicao das notas, contagem em risco e o ranking de alunos
    (media por ano + tendencia + faltas + flag de risco). Base da tela inicial.
    """
    if df.empty:
        return []

    medias = media_geral_por_aluno_ano(df)
    faltas = faltas_por_aluno_turma_ano(df)
    anos = sorted(c for c in medias.columns if c != "turma_atual")
    risco = _risco_por_aluno(df)
    curso_por_turma = df.drop_duplicates("turma").set_index("turma")["curso"].to_dict()
    matricula_por_aluno = df.drop_duplicates("aluno").set_index("aluno")["matricula"].to_dict()

    alunos = []
    for aluno, row in medias.iterrows():
        vals = {a: row.get(a) for a in anos}
        latest, trend = _latest_e_tendencia(vals, anos)
        faltas_vals = {a: faltas.loc[aluno].get(a) for a in anos} if aluno in faltas.index else {}
        faltas_latest, _ = _latest_e_tendencia(faltas_vals, anos)
        if trend is None:
            tend_dir = "flat"
        elif trend > 0.05:
            tend_dir = "up"
        elif trend < -0.05:
            tend_dir = "down"
        else:
            tend_dir = "flat"
        alunos.append({
            "aluno": aluno,
            "matricula": matricula_por_aluno.get(aluno, ""),
            "turma": row["turma_atual"],
            "medias": [vals[a] for a in anos],
            "latest": latest,
            "trend": trend,
            "tend_dir": tend_dir,
            "faltas": int(faltas_latest) if faltas_latest is not None else None,
            "risco": risco.get(aluno, False),
        })

    turmas = []
    for nome_turma in sorted(set(a["turma"] for a in alunos if a["turma"] is not None)):
        do_turma = [a for a in alunos if a["turma"] == nome_turma]
        do_turma.sort(key=lambda a: (a["latest"] is None, -(a["latest"] or 0)))
        latests = [a["latest"] for a in do_turma if a["latest"] is not None]
        media = sum(latests) / len(latests) if latests else None

        turmas.append({
            "turma": nome_turma,
            "curso": curso_por_turma.get(nome_turma, ""),
            "num_alunos": len(do_turma),
            "media": media,
            "num_risco": sum(1 for a in do_turma if a["risco"]),
            "quartis": _quartis(latests),
            "alunos": do_turma,
            "anos": [int(a) for a in anos],
        })

    # progressao escolar: 6º->9º Ano, depois 1ª->3ª Série do EM
    turmas.sort(key=lambda t: _ordem_turma(t["turma"], t["curso"]))
    return turmas


def resumo_geral(turmas: list[dict]) -> dict:
    """Numeros-sintese pra faixa do topo: media geral, % acima de 6, total em
    risco e maior queda (tendencia mais negativa) entre todos os alunos."""
    latests, trends, em_risco = [], [], 0
    for t in turmas:
        em_risco += t["num_risco"]
        for a in t["alunos"]:
            if a["latest"] is not None:
                latests.append(a["latest"])
            if a["trend"] is not None:
                trends.append(a["trend"])
    return {
        "media_geral": sum(latests) / len(latests) if latests else None,
        "pct_acima_6": round(sum(1 for v in latests if v >= 6) / len(latests) * 100) if latests else None,
        "em_risco": em_risco,
        "maior_queda": min(trends) if trends else None,
    }


# colunas de identificacao/derivadas - tudo mais em consolidado.csv e nota de
# um instrumento de avaliacao especifico (varia por disciplina/periodo: P1,
# P2, TRAB1-5, REC1-2, EXM, PD, R1, R2...), entao a lista e descoberta em
# tempo de execucao em vez de fixada aqui.
COLUNAS_INFO = {
    "aluno", "matricula", "curso", "ano_letivo", "periodo", "serie_turma",
    "disciplina", "Média do Período", "Situação", "Total de Faltas",
    "nota", "faltas", "turma",
}


def notas_detalhadas_aluno(df: pd.DataFrame, matricula: str) -> tuple[list[dict], list[str]]:
    """Uma linha por (ano, periodo, disciplina) com a nota de cada
    instrumento preenchido - prova (P1/P2/...), trabalho, recuperacao (REC1/
    REC2) - lado a lado, para comparar visualmente antes/depois da
    recuperacao em vez de so a media final do periodo.
    """
    aluno_df = df[df["matricula"] == matricula].copy()
    aluno_df["ordem"] = aluno_df["periodo"].map(ORDEM_PERIODO).fillna(9)
    aluno_df = aluno_df.sort_values(["ano_letivo", "ordem", "disciplina"])

    candidatas = [c for c in df.columns if c not in COLUNAS_INFO]
    instrumentos = [c for c in candidatas if aluno_df[c].notna().any()]

    colunas = ["ano_letivo", "periodo", "disciplina"] + instrumentos + ["nota", "Situação"]
    linhas = (
        aluno_df[colunas]
        .rename(columns={"nota": "media_periodo", "Situação": "situacao"})
        .to_dict("records")
    )
    return linhas, instrumentos
