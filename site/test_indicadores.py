"""Checagem minima dos indicadores. Roda sem servidor nem dados reais:
python site/test_indicadores.py
"""
import pandas as pd

from indicadores import (
    alerta_descolamento,
    alunos_em_risco,
    cruzamento_faltas_notas,
    faltas_por_aluno_turma_ano,
    medias_por_aluno_disciplina_ano,
    resumo_anual_aluno,
    trajetoria_aluno,
)


def _base():
    return pd.DataFrame([
        # Ana: nota caindo (8 -> 6) e faltas subindo (1 -> 5) - deve entrar em risco
        {"matricula": "1", "aluno": "Ana", "turma": "6A", "disciplina": "Matemática", "ano_letivo": 2023, "periodo": "1º Trimestre", "nota": 8.0, "faltas": 1},
        {"matricula": "1", "aluno": "Ana", "turma": "6A", "disciplina": "Matemática", "ano_letivo": 2024, "periodo": "1º Trimestre", "nota": 6.0, "faltas": 5},
        # Bruno: nota subindo e faltas caindo - nao deve entrar em risco
        {"matricula": "2", "aluno": "Bruno", "turma": "6A", "disciplina": "Matemática", "ano_letivo": 2023, "periodo": "1º Trimestre", "nota": 5.0, "faltas": 4},
        {"matricula": "2", "aluno": "Bruno", "turma": "6A", "disciplina": "Matemática", "ano_letivo": 2024, "periodo": "1º Trimestre", "nota": 7.0, "faltas": 1},
        # linha de Exame Final - nao deve contaminar a media de periodos regulares
        {"matricula": "1", "aluno": "Ana", "turma": "6A", "disciplina": "Matemática", "ano_letivo": 2024, "periodo": "Exame Final", "nota": 2.0, "faltas": 0},
    ])


def test_medias_ignora_exame_final():
    medias = medias_por_aluno_disciplina_ano(_base())
    assert medias.loc[("Ana", "Matemática"), 2024] == 6.0  # nao 4.0 (media com o Exame Final)


def test_faltas_soma_todos_os_periodos():
    faltas = faltas_por_aluno_turma_ano(_base())
    assert faltas.loc["Ana", 2024] == 5  # so tem a linha do Exame Final em 2024, faltas=0 la + 5 do trimestre
    assert faltas.loc["Ana", "turma_atual"] == "6A"


def test_faltas_agrupa_por_aluno_mesmo_com_turma_mudando():
    # Carla muda de turma entre os anos (progressao normal) - a evolucao tem
    # que ficar numa unica linha, nao quebrar em uma linha por turma.
    df = pd.DataFrame([
        {"aluno": "Carla", "turma": "6A", "disciplina": "Matemática", "ano_letivo": 2023, "periodo": "1º Trimestre", "nota": 7.0, "faltas": 2},
        {"aluno": "Carla", "turma": "7A", "disciplina": "Matemática", "ano_letivo": 2024, "periodo": "1º Trimestre", "nota": 7.5, "faltas": 3},
    ])
    faltas = faltas_por_aluno_turma_ano(df)
    assert len(faltas) == 1
    assert faltas.loc["Carla", 2023] == 2
    assert faltas.loc["Carla", 2024] == 3
    assert faltas.loc["Carla", "turma_atual"] == "7A"


def test_cruzamento_e_risco():
    cruz = cruzamento_faltas_notas(_base())
    ana = cruz[cruz["aluno"] == "Ana"].iloc[0]
    assert ana["delta_nota"] == -2.0
    assert ana["delta_faltas"] == 4

    risco = alunos_em_risco(cruz)
    assert set(risco["aluno"]) == {"Ana"}


def _base_turma():
    # Turma 7B, 1 disciplina (media do aluno = a propria nota, simplifica o calculo
    # esperado a mao). Xavier despenca de 2023 pra 2024, Yara e Zeca ficam estaveis.
    linhas = []
    for matricula, aluno, nota_2023, nota_2024 in [
        ("X1", "Xavier", 8.0, 5.0),
        ("Y1", "Yara", 6.0, 6.0),
        ("Z1", "Zeca", 4.0, 7.0),
    ]:
        linhas.append({"matricula": matricula, "aluno": aluno, "turma": "7B", "disciplina": "Português",
                        "ano_letivo": 2023, "periodo": "1º Trimestre", "nota": nota_2023, "faltas": 2})
        linhas.append({"matricula": matricula, "aluno": aluno, "turma": "7B", "disciplina": "Português",
                        "ano_letivo": 2024, "periodo": "1º Trimestre", "nota": nota_2024, "faltas": 2})
    return pd.DataFrame(linhas)


def test_resumo_anual_z_score_e_percentil():
    resumo = resumo_anual_aluno(_base_turma(), "X1")
    r2023, r2024 = resumo[0], resumo[1]

    # turma 2023: [8,6,4] -> media 6, desvio amostral 2
    assert r2023["media_aluno"] == 8.0
    assert round(r2023["turma_media"], 4) == 6.0
    assert round(r2023["z"], 4) == 1.0
    assert round(r2023["percentil"], 2) == round(2 / 3 * 100, 2)  # melhor que Yara e Zeca

    # turma 2024: [5,6,7] -> media 6, desvio amostral 1 - Xavier caiu pro fundo
    assert r2024["media_aluno"] == 5.0
    assert round(r2024["z"], 4) == -1.0
    assert r2024["percentil"] == 0.0  # ninguem abaixo dele


def test_alerta_descolamento_dispara_quando_z_despenca():
    resumo = resumo_anual_aluno(_base_turma(), "X1")
    assert alerta_descolamento(resumo) is not None

    resumo_estavel = resumo_anual_aluno(_base_turma(), "Y1")
    assert alerta_descolamento(resumo_estavel) is None


def test_trajetoria_aluno_um_ponto_por_periodo():
    pontos, disciplinas = trajetoria_aluno(_base_turma(), "X1")
    assert len(pontos) == 2
    assert pontos[0]["media_aluno"] == 8.0
    assert pontos[1]["media_aluno"] == 5.0
    assert disciplinas["Português"] == [8.0, 5.0]


if __name__ == "__main__":
    test_medias_ignora_exame_final()
    test_faltas_soma_todos_os_periodos()
    test_faltas_agrupa_por_aluno_mesmo_com_turma_mudando()
    test_cruzamento_e_risco()
    test_resumo_anual_z_score_e_percentil()
    test_alerta_descolamento_dispara_quando_z_despenca()
    test_trajetoria_aluno_um_ponto_por_periodo()
    print("OK - indicadores conferem")
