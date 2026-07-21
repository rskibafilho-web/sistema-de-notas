"""Consolida os CSVs de dados_exportados/{ano}/*.csv numa base unica para o site.

Uso: python scripts/consolidar.py
Roda de novo sempre que houver coleta nova (scripts/coletar.py) antes de olhar
o site - ele le a base gerada aqui, nao os CSVs brutos direto.
"""
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
ENTRADA = BASE_DIR / "dados_exportados"
SAIDA = BASE_DIR / "site" / "dados" / "consolidado.csv"
LISTA_EXCLUSAO = BASE_DIR / "scripts" / "disciplinas_excluidas.txt"


def carregar_disciplinas_excluidas() -> list[str]:
    if not LISTA_EXCLUSAO.exists():
        return []
    linhas = LISTA_EXCLUSAO.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]


def carregar_tudo() -> pd.DataFrame:
    arquivos = sorted(ENTRADA.glob("*/*.csv"))
    if not arquivos:
        sys.exit(f"Nenhum CSV encontrado em {ENTRADA} - rode scripts/coletar.py primeiro.")

    partes = [pd.read_csv(f, dtype=str) for f in arquivos]
    df = pd.concat(partes, ignore_index=True)

    df["nota"] = pd.to_numeric(df.get("Média do Período"), errors="coerce")
    df["faltas"] = pd.to_numeric(df.get("Total de Faltas"), errors="coerce").fillna(0)
    df["ano_letivo"] = pd.to_numeric(df["ano_letivo"], errors="coerce").astype("Int64")
    df["turma"] = df["serie_turma"]

    # colunas de instrumento de avaliacao (PRV1, TRAB1-5, REC1-2, e variantes
    # que vao aparecendo) sao numericas mas chegam como texto (lemos tudo com
    # dtype=str acima). Convertendo aqui na fonte, o CSV consolidado sai com
    # tipo consistente - sem isso, leitura em chunks (low_memory) do pandas
    # pode inferir tipos diferentes por pedaco do arquivo e misturar str/float
    # na mesma coluna, quebrando qualquer formatacao numerica no site.
    colunas_texto = {"aluno", "matricula", "curso", "periodo", "serie_turma", "disciplina",
                      "Situação", "turma", "ano_letivo", "Média do Período", "Total de Faltas",
                      "nota", "faltas"}
    for col in df.columns:
        if col not in colunas_texto:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # atividades do INTEGRAL (contraturno) nao contam pra media/indicadores academicos
    antes = len(df)
    df = df[~df["disciplina"].str.contains(r"\(INTEGRAL\)", case=False, na=False)]
    print(f"excluidas {antes - len(df)} linhas de disciplinas (INTEGRAL)")

    excluidas = carregar_disciplinas_excluidas()
    if excluidas:
        antes = len(df)
        df = df[~df["disciplina"].isin(excluidas)]
        print(f"excluidas {antes - len(df)} linhas de {excluidas} (ver scripts/disciplinas_excluidas.txt)")
    return df


def main() -> None:
    df = carregar_tudo()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    print(f"{len(df)} linhas, {df['ano_letivo'].nunique()} anos, {df['aluno'].nunique()} alunos -> {SAIDA}")


if __name__ == "__main__":
    main()
