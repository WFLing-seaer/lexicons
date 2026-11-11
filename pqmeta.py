#!/usr/bin/env python3
"""lexicons 编译产物的 parquet 元数据：写进产物（`.pq`）与读回来（决定要不要重编）。

元数据只描述**编译数据源**，不参与词库数据本身。键名带 `lexicon.` 前缀：

    lexicon.meta_version     元数据字段的版本（字段含义变了就 +1，老产物自动失效重编）
    lexicon.pipeline         写盘管线指纹（awkward/pyarrow 版本），不一致就重编
    lexicon.source_name      源文件名（不含路径，带扩展名）
    lexicon.source_size      源文件字节数
    lexicon.source_mtime_ns  源文件修改时间（Unix 纳秒时间戳）
    lexicon.source_sha256    源文件原始字节的 sha256（小写 hex）
    lexicon.rows             产物行数（纯信息，不参与判定）

存放位置是 parquet 的 key-value metadata（`FileMetaData.key_value_metadata`），
任何读 parquet 的工具都能只读文件 footer 就看到，不用碰数据页：

    >>> pyarrow.parquet.read_metadata("词.pq").metadata[b"lexicon.source_sha256"]
    b"..."
    >>> awkward.from_parquet("词.pq")   # 数据照旧，元数据不影响读出来的数组

awkward 的 `ak.to_parquet` 不接受自定义元数据，所以这里复刻它的写盘路径：
同样的 layout/array 转换 + 同样的 `ParquetWriter` 参数，只在写之前往 Arrow schema 的
metadata 里多塞几个键。这样数据页字节与 `ak.to_parquet` 逐字节相同——`_TABLE_OPTS` /
`_WRITER_OPTS` 必须与 `TESTED_AWKWARD` 版本的 `ak.to_parquet` 默认值一一对应，改了就得
同步改 `META_VERSION`（元数据指纹会变，全部产物自动重编）。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sys

import awkward as ak
import pyarrow
import pyarrow.parquet as pq

#: 复刻写盘参数所依据的 awkward 版本（requirements.txt 里 pin 的死版本）
TESTED_AWKWARD = "2.9.0"
#: 元数据字段的版本；字段含义/增减有变化时必须 +1，否则老产物会被误判成「最新」
META_VERSION = "1"
#: parquet key-value 元数据的键前缀
PREFIX = "lexicon."
_PREFIX_BYTES = PREFIX.encode()
#: 判定「产物是否过期」必须读到的字段
_REQUIRED_KEYS = ("meta_version", "pipeline", "source_name", "source_size", "source_mtime_ns", "source_sha256")

#: 与 ak.to_parquet 的默认值对应：list_to32, string_to32, bytestring_to32, emptyarray_to,
#: categorical_as_dictionary, extensionarray, count_nulls
_TABLE_OPTS = (False, True, True, None, False, True, True)
#: 与 ak.to_parquet 传给 pyarrow.parquet.ParquetWriter 的默认值一一对应
_WRITER_OPTS = {
    "flavor": None,
    "version": "2.4",
    "use_dictionary": False,
    "compression": "zstd",
    "write_statistics": True,
    "use_deprecated_int96_timestamps": None,
    "compression_level": None,
    "use_byte_stream_split": False,
    "data_page_version": "1.0",
    "use_compliant_nested_type": False,
    "data_page_size": None,
    "coerce_timestamps": None,
}
#: 与 ak.to_parquet 的 row_group_size 默认值一致
_ROW_GROUP_SIZE = 64 * 1024 * 1024

try:  # awkward 的内部工具：把带扩展类型的 table 换成 pyarrow 原生 table
    from awkward._connect.pyarrow import convert_awkward_arrow_table_to_native as _to_native
except ImportError:  # pragma: no cover - 理论上不会发生
    _to_native = None
try:  # 与 ak.to_parquet 内部用的同一对函数（layout / table 转换）
    import awkward.operations.ak_to_arrow_table as _to_arrow_table  # noqa: PLC0415
    import awkward.operations.ak_to_layout as _to_layout  # noqa: PLC0415
except ImportError:  # pragma: no cover - 理论上不会发生
    _to_arrow_table = None
    _to_layout = None

_WARNED: set[str] = set()


def _warn_once(tag: str, message: str) -> None:
    if tag in _WARNED:
        return
    _WARNED.add(tag)
    print(f"警告: {message}", file=sys.stderr, flush=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pipeline_fingerprint(extra: dict[str, str] | None = None) -> str:
    """写盘管线指纹：awkward/pyarrow 换版本（产物字节可能跟着变）就会不一致。

    `extra` 用来额外掺进调用方认为会影响产物的东西（compile.py 会掺编译模块的内容 hash
    与拼音库版本），键名保持稳定，值里不要放时间戳之类每次都变的东西。
    """
    parts = [f"meta={META_VERSION}", f"awkward={ak.__version__}", f"pyarrow={pyarrow.__version__}"]
    parts += [f"{key}={value}" for key, value in sorted((extra or {}).items())]
    return ";".join(parts)


def build_metadata(
    *,
    source_name: str,
    source_size: int,
    source_mtime_ns: int,
    source_sha256: str,
    rows: int,
    pipeline: str | None = None,
) -> dict[str, str]:
    """拼出要写进产物的元数据（键不带前缀，写入时统一加）。"""
    return {
        "meta_version": META_VERSION,
        "pipeline": pipeline if pipeline is not None else pipeline_fingerprint(),
        "source_name": source_name,
        "source_size": str(source_size),
        "source_mtime_ns": str(source_mtime_ns),
        "source_sha256": source_sha256,
        "rows": str(rows),
    }


def read_metadata(pq_path: pathlib.Path, *, pipeline: str) -> dict[str, str] | None:
    """读产物里的 `lexicon.*` 元数据（只读 footer，不碰数据页）。

    产物不存在、没有元数据、元数据版本/管线指纹不符、字段缺失或损坏、或文件本身读不出来
    （半截文件之类）一律返回 None —— 对调用方来说都等于「不知道它新不新，重编吧」。
    """
    path = pathlib.Path(pq_path)
    if not path.is_file():
        return None
    try:
        raw = pq.read_metadata(str(path)).metadata or {}
    except Exception:  # noqa: BLE001 - 坏文件/非 parquet 都当「没有元数据」
        return None
    meta: dict[str, str] = {}
    for key, value in raw.items():
        if not key.startswith(_PREFIX_BYTES):
            continue
        try:
            meta[key[len(_PREFIX_BYTES):].decode()] = value.decode()
        except UnicodeDecodeError:
            return None
    if any(k not in meta for k in _REQUIRED_KEYS):
        return None
    if meta["meta_version"] != META_VERSION or meta["pipeline"] != pipeline:
        return None
    try:
        int(meta["source_size"])
        int(meta["source_mtime_ns"])
    except ValueError:
        return None
    return meta


def _metadata_capable() -> bool:
    return (
        _to_native is not None
        and hasattr(_to_layout, "_impl")
        and hasattr(_to_arrow_table, "_impl")
    )


def _write_with_metadata(array: ak.Array, destination: pathlib.Path, metadata: dict[str, str]) -> None:
    """复刻 `ak.to_parquet` 的写盘过程，并在 Arrow schema 里补上 `lexicon.*` 键值元数据。"""
    if ak.__version__ != TESTED_AWKWARD:
        _warn_once(
            f"version-{ak.__version__}",
            f"写盘参数是按 awkward {TESTED_AWKWARD} 的 ak.to_parquet 默认值复刻的，"
            f"当前是 {ak.__version__}：产物依然可读，但与 ak.to_parquet 的字节可能不再一致，"
            "升级后请对一次 `python compile.py <某个源文件> --force` 的产物字节",
        )
    layout = _to_layout._impl(
        array,
        allow_record=True,
        allow_unknown=False,
        none_policy="error",
        regulararray=True,
        use_from_iter=True,
        primitive_policy="error",
        string_policy="as-characters",
    )
    table = _to_arrow_table._impl(layout, *_TABLE_OPTS)
    table = _to_native(table)
    schema_metadata = dict(table.schema.metadata or {})
    for name, value in metadata.items():
        schema_metadata[(PREFIX + name).encode()] = str(value).encode()
    table = table.replace_schema_metadata(schema_metadata)
    with pq.ParquetWriter(str(destination), table.schema, **_WRITER_OPTS) as writer:
        writer.write_table(table, row_group_size=_ROW_GROUP_SIZE)


def write_parquet(array: ak.Array, destination: pathlib.Path, metadata: dict[str, str] | None = None) -> None:
    """把 array 写成 parquet，`metadata` 以 `lexicon.` 前缀塞进文件的 key-value 元数据。

    先写同目录临时文件再原子替换：编译中途挂掉不会留下「半个产物」骗过下次的跳过判断。
    """
    destination = pathlib.Path(destination)
    tmp = destination.with_name(f".{destination.name}.tmp")
    try:
        if metadata:
            if not _metadata_capable():
                _warn_once(
                    "fallback",
                    f"当前 awkward {ak.__version__} 写不出自定义元数据，产物里不会带 lexicon.* 元数据"
                    "（下次编译会重编这些文件）",
                )
                ak.to_parquet(array, tmp)
            else:
                try:
                    _write_with_metadata(array, tmp, metadata)
                except (AttributeError, TypeError) as exc:
                    _warn_once(
                        "fallback-api",
                        f"复刻 ak.to_parquet 的写盘路径失败（{exc!r}），改为不带元数据地写产物"
                        "（下次编译会重编这些文件）；请检查 awkward 版本是否为 "
                        f"{TESTED_AWKWARD}",
                    )
                    ak.to_parquet(array, tmp)
        else:
            ak.to_parquet(array, tmp)
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            tmp.unlink()
