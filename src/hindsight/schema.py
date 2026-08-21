from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa

from hindsight.normalize import (
    OPENFDA_KEY,
    ORDINAL,
    PIPELINE_COLUMNS,
    REPORT_ID,
    SEQ,
    TABLES,
    OpenfdaDimension,
    split,
)


SCHEMA_DIR = Path("schema")


COLUMN_TYPES = {REPORT_ID: "string", ORDINAL: "int64", SEQ: "int64", OPENFDA_KEY: "string"}


SCALARS: dict[type, str] = {str: "string", bool: "bool", int: "int64", float: "double"}

ARROW_SCALARS: dict[str, pa.DataType] = {
    "string": pa.string(),
    "bool": pa.bool_(),
    "int64": pa.int64(),
    "double": pa.float64(),
}


UNOBSERVED = "string"


class SchemaError(Exception):
    pass


class SchemaConflict(SchemaError):
    pass


class UnwritableSchema(SchemaError):
    pass


class UnreadableSchema(SchemaError):
    pass


class UnknownField(SchemaError):
    pass


@dataclass(slots=True)
class ListOf:
    item: "Node | None" = None


@dataclass(slots=True)
class Struct:
    fields: dict[str, "Node"] = field(default_factory=dict)


Node = str | ListOf | Struct


def _describe(node: Node | None) -> str:
    if node is None:
        return "unobserved"

    if isinstance(node, ListOf):
        return f"list<{_describe(node.item)}>"

    if isinstance(node, Struct):
        return f"struct<{', '.join(sorted(node.fields))}>"

    return node


def _observe(value: object, known: Node | None, path: str) -> Node:
    if value is None:
        return known

    if isinstance(value, dict):
        if known is not None and not isinstance(known, Struct):
            raise SchemaConflict(
                f"{path} é um objeto aqui e {_describe(known)} em outro ponto da "
                f"mesma partição. O Arrow guarda um tipo por coluna."
            )

        node = known if isinstance(known, Struct) else Struct()

        for name, item in value.items():
            node.fields[name] = _observe(item, node.fields.get(name), f"{path}.{name}")

        return node

    if isinstance(value, list):
        if known is not None and not isinstance(known, ListOf):
            raise SchemaConflict(
                f"{path} é um array aqui e {_describe(known)} em outro ponto da "
                f"mesma partição. O Arrow guarda um tipo por coluna."
            )

        node = known if isinstance(known, ListOf) else ListOf()

        for item in value:
            node.item = _observe(item, node.item, f"{path}[]")

        return node

    scalar = SCALARS.get(type(value))

    if scalar is None:
        raise SchemaConflict(
            f"{path} é um {type(value).__name__}, que não é algo que JSON produz. "
            f"O stream deveria devolver só str, bool, int, float, list, dict "
            f"e None."
        )

    if known is None:
        return scalar

    if known != scalar:
        raise SchemaConflict(
            f"{path} é {scalar} aqui e {_describe(known)} em outro ponto da mesma "
            f"partição. Nenhum é convertido no outro — registre quais "
            f"relatórios divergem e decida, em vez de alargar em silêncio."
        )

    return scalar


def _arrow(node: Node | None, path: str) -> pa.DataType:
    if node is None:
        return ARROW_SCALARS[UNOBSERVED]

    if isinstance(node, ListOf):
        return pa.list_(_arrow(node.item, f"{path}[]"))

    if isinstance(node, Struct):
        if not node.fields:
            raise UnwritableSchema(
                f"{path} foi um objeto em todo registro que o tinha, e vazio em "
                f"todos. O Parquet não escreve struct sem campos, entao isso "
                f"precisa de uma decisão — provavelmente descartar o campo, o "
                f"que nenhum passo de inferência decide em silêncio."
            )

        return pa.struct(
            [
                pa.field(name, _arrow(node.fields[name], f"{path}.{name}"))
                for name in sorted(node.fields)
            ]
        )

    return ARROW_SCALARS[node]


@dataclass(frozen=True)
class Schemas:
    tables: dict[str, pa.Schema]

    def __getitem__(self, table: str) -> pa.Schema:
        return self.tables[table]

    def has_column(self, table: str, column: str) -> bool:
        return column in self.tables[table].names


def _pin_pipeline_columns(nodes: dict[str, Node | None], table: str) -> None:
    for name in PIPELINE_COLUMNS[table]:
        declared = COLUMN_TYPES[name]
        observed = nodes.get(name)

        if observed is not None and observed != declared:
            raise SchemaConflict(
                f"{table}.{name} é uma coluna que este pipeline escreve e deveria ser "
                f"{declared}, mas chegou como {_describe(observed)}. Ou o "
                f"`split` parou de escrever o que diz escrever, ou o openFDA "
                f"passou a ter um campo de fonte com esse nome."
            )

        nodes[name] = declared


def infer(reports: Iterable[dict]) -> Schemas:
    observed: dict[str, dict[str, Node]] = {table: {} for table in TABLES}
    dimension = OpenfdaDimension()

    for ordinal, report in enumerate(reports, start=1):
        for table, rows in split(report, dimension, ordinal).by_table().items():
            known = observed[table]

            for row in rows:
                for name, value in row.items():
                    known[name] = _observe(value, known.get(name), f"{table}.{name}")

    for table, nodes in observed.items():
        _pin_pipeline_columns(nodes, table)

    return Schemas(
        {
            table: pa.schema(
                [
                    pa.field(name, _arrow(nodes[name], f"{table}.{name}"))
                    for name in sorted(nodes)
                ]
            )
            for table, nodes in observed.items()
        }
    )


def _to_json(arrow_type: pa.DataType) -> object:
    if pa.types.is_list(arrow_type):
        return [_to_json(arrow_type.value_type)]

    if pa.types.is_struct(arrow_type):
        return {child.name: _to_json(child.type) for child in arrow_type}

    for name, scalar in ARROW_SCALARS.items():
        if arrow_type.equals(scalar):
            return name

    raise UnwritableSchema(f"{arrow_type} não tem representacao num arquivo de schema.")


def _from_json(node: object, path: str) -> pa.DataType:
    if isinstance(node, list):
        if len(node) != 1:
            raise UnreadableSchema(
                f"{path}: um tipo lista se escreve como array de um elemento nomeando "
                f"o tipo do item, achei {len(node)} elementos."
            )

        return pa.list_(_from_json(node[0], f"{path}[]"))

    if isinstance(node, dict):
        return pa.struct(
            [
                pa.field(name, _from_json(child, f"{path}.{name}"))
                for name, child in node.items()
            ]
        )

    if node in ARROW_SCALARS:
        return ARROW_SCALARS[node]

    raise UnreadableSchema(
        f"{path}: {node!r} não é um tipo que este módulo escreve "
        f"({', '.join(sorted(ARROW_SCALARS))}, um objeto, ou array de um elemento)."
    )


def save(path: Path, schemas: Schemas, *, source: dict) -> None:
    document = {
        "source": source,
        "tables": {
            table: {column.name: _to_json(column.type) for column in schema}
            for table, schema in schemas.tables.items()
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n")


def load(path: Path) -> Schemas:
    try:
        document = json.loads(path.read_text())
        tables = document["tables"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise UnreadableSchema(f"{path} is not a readable schema file: {exc}") from exc

    missing = set(TABLES) - set(tables)

    if missing:
        raise UnreadableSchema(
            f"{path} has no schema for {sorted(missing)}. Delete it and re-infer "
            f"— a partial schema silently drops whichever table it omits."
        )

    return Schemas(
        {
            table: pa.schema(
                [
                    pa.field(name, _from_json(node, f"{table}.{name}"))
                    for name, node in columns.items()
                ]
            )
            for table, columns in tables.items()
        }
    )


def _is_nested(arrow_type: pa.DataType) -> bool:
    return pa.types.is_struct(arrow_type) or pa.types.is_list(arrow_type)


def _enforce_nested(value: object, arrow_type: pa.DataType, table: str, path: str) -> None:
    if pa.types.is_struct(arrow_type):
        if not isinstance(value, dict):
            return

        known = {child.name: child.type for child in arrow_type}
        unknown = value.keys() - known.keys()

        if unknown:
            raise UnknownField(
                f"{table}: {path} carries {sorted(unknown)}, which the schema "
                f"has no field for. Arrow would drop it and write the file "
                f"anyway. Re-infer the schema for this partition."
            )

        for name, child_type in known.items():
            child = value.get(name)

            if child is not None and _is_nested(child_type):
                _enforce_nested(child, child_type, table, f"{path}.{name}")

        return

    if isinstance(value, list) and _is_nested(arrow_type.value_type):
        for position, item in enumerate(value):
            if item is not None:
                _enforce_nested(
                    item, arrow_type.value_type, table, f"{path}[{position}]"
                )


def enforce(rows: list[dict], schema: pa.Schema, table: str) -> None:
    names = set(schema.names)
    nested = {column.name: column.type for column in schema if _is_nested(column.type)}

    for row in rows:
        unknown = row.keys() - names

        if unknown:
            raise UnknownField(
                f"{table}: a row carries {sorted(unknown)}, which the schema has "
                f"no column for. Arrow would drop the field and write valid "
                f"Parquet with matching row counts — this is the L-005 failure, "
                f"caught. Re-infer the schema for this partition."
            )

        for name, arrow_type in nested.items():
            value = row.get(name)

            if value is not None:
                _enforce_nested(value, arrow_type, table, name)
