"""Storage knob: how a table sits on disk (format x compression).

Every format is read with Apache Arrow's native readers so the reader library stays
constant across formats; only the on-disk representation changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.json as pajson
import pyarrow.parquet as pq

# name -> (format, codec, file suffix)
STORAGES: dict[str, tuple[str, str | None, str]] = {
    "csv": ("csv", None, ".csv"),
    "csv-zstd": ("csv", "zstd", ".csv.zst"),
    "json": ("json", None, ".ndjson"),
    "json-zstd": ("json", "zstd", ".ndjson.zst"),
    "parquet": ("parquet", "none", ".parquet"),
    "parquet-snappy": ("parquet", "snappy", ".parquet"),
    "parquet-zstd": ("parquet", "zstd", ".parquet"),
}
DEFAULT_STORAGE = "parquet-snappy"
STORAGE_LABELS = {
    "csv": "CSV", "csv-zstd": "CSV + Zstd", "json": "JSON lines", "json-zstd": "JSON lines + Zstd",
    "parquet": "Parquet (uncompressed)", "parquet-snappy": "Parquet + Snappy", "parquet-zstd": "Parquet + Zstd",
}


def table_path(directory: Path, table: str, storage: str) -> Path:
    return directory / f"{table}__{storage}{STORAGES[storage][2]}"


def write_table(tbl: pa.Table, path: Path, storage: str) -> None:
    fmt, codec, _ = STORAGES[storage]
    tmp = path.with_name(path.name + ".tmp")
    if fmt == "parquet":
        pq.write_table(tbl, tmp, compression=codec, row_group_size=256 * 1024)
    elif fmt == "csv":
        sink = pa.CompressedOutputStream(str(tmp), codec) if codec else pa.OSFile(str(tmp), "wb")
        with sink:
            pacsv.write_csv(tbl, sink)
    elif fmt == "json":
        sink = pa.CompressedOutputStream(str(tmp), codec) if codec else pa.OSFile(str(tmp), "wb")
        with sink:
            _write_ndjson(tbl, sink)
    tmp.replace(path)


def _write_ndjson(tbl: pa.Table, sink) -> None:
    names = tbl.column_names
    for batch in tbl.to_batches(max_chunksize=200_000):
        cols = []
        for name, col in zip(names, batch.columns):
            values = col.to_pylist()
            if pa.types.is_string(col.type) or pa.types.is_large_string(col.type):
                cols.append([json.dumps(v) for v in values])
            else:
                cols.append([str(v) for v in values])
        keys = [json.dumps(n) + ":" for n in names]
        lines = ["{" + ",".join(k + v for k, v in zip(keys, row)) + "}" for row in zip(*cols)]
        sink.write(("\n".join(lines) + "\n").encode("utf-8"))


def read_table(path: Path, storage: str, schema: pa.Schema, columns: list[str] | None = None,
               threads: int = 1) -> pa.Table:
    """Read `columns` of a table stored with `storage`. `threads` > 1 enables Arrow's parallel readers."""
    fmt, codec, _ = STORAGES[storage]
    use_threads = threads > 1
    if fmt == "parquet":
        return pq.read_table(path, columns=columns, use_threads=use_threads)
    source = pa.CompressedInputStream(pa.OSFile(str(path)), codec) if codec else str(path)
    if fmt == "csv":
        conv = pacsv.ConvertOptions(column_types=schema, include_columns=columns)
        return pacsv.read_csv(source, read_options=pacsv.ReadOptions(use_threads=use_threads), convert_options=conv)
    sub = schema if columns is None else pa.schema([schema.field(c) for c in columns])
    parse = pajson.ParseOptions(explicit_schema=sub, unexpected_field_behavior="ignore")
    tbl = pajson.read_json(source, read_options=pajson.ReadOptions(use_threads=use_threads), parse_options=parse)
    return tbl.select(columns) if columns else tbl
