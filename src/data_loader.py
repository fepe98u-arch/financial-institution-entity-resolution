"""분개장 파일(CSV/Excel)을 Polars DataFrame으로 읽어들이는 모듈."""

from pathlib import Path

import polars as pl

SUPPORTED_EXTENSIONS = ("csv", "xlsx", "xls")


def _get_extension(file_obj) -> str:
    name = getattr(file_obj, "name", None) or str(file_obj)
    return name.lower().rsplit(".", 1)[-1]


def load_journal_file(file_obj) -> pl.DataFrame:
    """CSV 또는 Excel 파일을 Polars DataFrame으로 읽는다.

    file_obj: Streamlit UploadedFile 객체 또는 파일 경로(str/Path).
    원본 파일은 읽기만 하고 수정하지 않는다.
    """
    suffix = _get_extension(file_obj)

    if suffix == "csv":
        return pl.read_csv(file_obj, infer_schema_length=10000, encoding="utf8-lossy")
    if suffix in ("xlsx", "xls"):
        return pl.read_excel(file_obj, engine="openpyxl")

    raise ValueError(f"지원하지 않는 파일 형식입니다: .{suffix} (csv, xlsx만 지원)")


def scan_journal_csv(path: str | Path) -> pl.LazyFrame:
    """디스크에 저장된 대용량 CSV를 Lazy로 스캔한다.

    Polars의 scan_csv는 파일 경로가 필요하므로 업로드 스트림이 아닌
    실제 파일에 대해서만 사용한다. Phase 1에서는 UI에 연결하지 않고,
    대용량 처리 단계(Phase 8)에서 사용할 예정이다.
    """
    return pl.scan_csv(path, infer_schema_length=10000, encoding="utf8-lossy")
