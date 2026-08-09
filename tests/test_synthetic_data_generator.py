from src.synthetic_data_generator import generate_synthetic_journal


def test_generate_synthetic_journal_row_count():
    df = generate_synthetic_journal(n_rows=200)
    assert df.height == 200


def test_generate_synthetic_journal_columns():
    df = generate_synthetic_journal(n_rows=10)
    assert set(df.columns) == {"전표번호", "전표일자", "거래처", "적요", "계정과목", "상대계정", "금액"}


def test_generate_synthetic_journal_reproducible_with_seed():
    df1 = generate_synthetic_journal(n_rows=50, seed=1)
    df2 = generate_synthetic_journal(n_rows=50, seed=1)
    assert df1.equals(df2)
