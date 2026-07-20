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

    # atividades do INTEGRAL (contraturno) nao contam pra media/indicadores academicos
    antes = len(df)
    df = df[~df["disciplina"].str.contains(r"\(INTEGRAL\)", case=False, na=False)]
    print(f"excluidas {antes - len(df)} linhas de disciplinas (INTEGRAL)")
    return df


def main() -> None:
    df = carregar_tudo()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    print(f"{len(df)} linhas, {df['ano_letivo'].nunique()} anos, {df['aluno'].nunique()} alunos -> {SAIDA}")


if __name__ == "__main__":
    main()
