"""Checagem minima do alinhamento de colunas do Espelho de Notas/Faltas.

Roda sem navegador nem rede: python scripts/test_coletar.py
Reproduz o caso real (aluno de exemplo, Matematica, 1o Trimestre - ver
MAPEAMENTO.md secao 5) que expos um desalinhamento de coluna: a versao
ingenua colocava "APR" em Total de Faltas e a nota em Situacao.
"""
from coletar import montar_linha, slugify


def test_linha_com_indice_numerico():
    headers = ["Disciplinas", "PRV1", "PRV2", "TRAB1", "TRAB2", "TRAB3", "TRAB4",
               "TRAB5", "REC1", "REC2", "EXM", "Média do Período", "Situação", "Total de Faltas"]
    celulas = ["1", "Matemática", "7.90", "5.80", "9.00", "", "", "", "", "", "", "", "7.40", "APR", "0"]
    info = {"Aluno": "Aluno Exemplo", "Matrícula": "00000000", "Período": "1º Trimestre"}

    linha = montar_linha(info, headers, celulas)

    assert linha["disciplina"] == "Matemática"
    assert linha["PRV1"] == "7.90"
    assert linha["PRV2"] == "5.80"
    assert linha["TRAB1"] == "9.00"
    assert linha["Média do Período"] == "7.40"
    assert linha["Situação"] == "APR"
    assert linha["Total de Faltas"] == "0"


def test_linha_sem_indice_numerico():
    headers = ["Disciplinas", "1º Trim", "2º Trim", "3º Trim", "Total de Faltas"]
    celulas = ["Arte", "0", "0", "1", "1"]

    linha = montar_linha({}, headers, celulas)

    assert linha["disciplina"] == "Arte"
    assert linha["1º Trim"] == "0"
    assert linha["3º Trim"] == "1"
    assert linha["Total de Faltas"] == "1"


def test_slugify():
    assert slugify("Ensino Fundamental II - 6º Ano") == "ensino_fundamental_ii_6o_ano"
    assert slugify("1ª Série - Matutino") == "1a_serie_matutino"


if __name__ == "__main__":
    test_linha_com_indice_numerico()
    test_linha_sem_indice_numerico()
    test_slugify()
    print("OK - alinhamento de colunas e slugify conferem")
