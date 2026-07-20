"""Calculo dos 3 indicadores pedidos, separado das rotas Flask para ser
testavel sem servidor (ver test_indicadores.py).
"""
import pandas as pd

PERIODOS_REGULARES = {"1º Trimestre", "2º Trimestre", "3º Trimestre"}


def filtrar(df: pd.DataFrame, turma: str = "", disciplina: str = "") -> pd.DataFrame:
    if turma:
        df = df[df["turma"] == turma]
    if disciplina:
        df = df[df["disciplina"] == disciplina]
    return df


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
