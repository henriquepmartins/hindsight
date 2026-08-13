"""Pass 1: the type of every field, read from every record and written down.

Arrow wants one schema for a whole file. JSON hands you 12,000 records that
disagree — a field is absent here, an empty list there, an object with three
keys in one report and five in the next. Something has to reconcile them, and
the only question is whether that something looked at all the records or at a
few of them.

The spike looked at `results[0]`, and every bug in L-005 followed: `companynumb`
gone from 89.6% of reports, `patient.summary` from 49.1%, `reportduplicate`
dropped outright. So the rule here (AD-011) is the opposite one, and it is
structural rather than optional:

> the schema is the union over **every** record, saved to a file, and pass 2
> writes against that file rather than against whatever it happens to see.

What that buys is not tidiness. `pa.Table.from_pylist` silently drops any key
the schema has no column for — measured, at the top level and inside structs
both — so a schema derived from a sample loses fields *quietly*, with valid
Parquet and matching row counts on the other side. `enforce()` turns that
silence into an exception, which only means anything because the schema it
enforces saw all 12,000 records.

The saved file is also the artifact M1's drift detection needs. Two exports,
two schema files, one `diff` — the mechanism does not have to be invented later,
which is why field names are sorted at every level: a diff between canonical
files shows what changed, and a diff between insertion-ordered files shows what
order the reports happened to arrive in.

**The file reads like a record with types where the values would be.** A JSON
string is a scalar, a JSON object is a struct, and a one-element JSON array is a
list of that type:

    "companynumb": "string"
    "primarysource": {"qualification": "string", "reportercountry": "string"}
    "brand_name": ["string"]

Nested objects stay structs and are never flattened (design.md): flattening
needs a separator convention, and every separator convention eventually meets a
field name containing the separator.

Unification is deliberately narrow. A field seen only as null, and a list seen
only empty, resolve to string — "string unless proven otherwise". Anything else
that disagrees raises, including `int64` against `double`: a project whose
schema bugs all came from quiet widening does not get to widen quietly. Every
FAERS scalar measured so far is a string (19,648,458 of them in T6), so a
conflict here is news, not routine.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa

from hindsight.normalize import (
    OPENFDA_KEY,
    PIPELINE_COLUMNS,
    REPORT_ID,
    SEQ,
    TABLES,
    OpenfdaDimension,
    split,
)


SCHEMA_DIR = Path("schema")

# The type of each column the pipeline writes itself. Declared rather than
# inferred, because inference has nothing to go on when they are null: `seq` is
# null on every row of a partition whose duplicates all arrived as bare objects,
# and that resolves to string there and int64 in the next partition — a column
# type that depends on which partition you read is the drift this file exists to
# detect, not to cause. Which table has which of them is normalize.py's to say.
COLUMN_TYPES = {REPORT_ID: "string", SEQ: "int64", OPENFDA_KEY: "string"}

# JSON produces exactly these. `bool` sits before `int` because `bool` is a
# subclass of `int` in Python, and this dict is keyed by exact type for that
# reason — an `isinstance` chain would type every True as int64.
SCALARS: dict[type, str] = {str: "string", bool: "bool", int: "int64", float: "double"}

ARROW_SCALARS: dict[str, pa.DataType] = {
    "string": pa.string(),
    "bool": pa.bool_(),
    "int64": pa.int64(),
    "double": pa.float64(),
}

# What a field resolves to when the corpus never showed its type: every value
# null, or every list empty. Not a guess about the data — a decision about which
# way to be wrong, and string is the only one that cannot lose information.
UNOBSERVED = "string"


# --- errors -----------------------------------------------------------------


class SchemaError(Exception):
    """Base for every failure in this module."""


class SchemaConflict(SchemaError):
    """One field arrived with two types that Arrow cannot hold in one column.

    Never resolved by widening. The path in the message is the field, at the
    depth it disagreed.
    """


class UnwritableSchema(SchemaError):
    """The inferred schema is valid Arrow but cannot be written to Parquet."""


class UnreadableSchema(SchemaError):
    """A saved schema file is not one this module wrote."""


class UnknownField(SchemaError):
    """A row carries a field the schema has no column for.

    The whole reason `enforce` exists: Arrow's own answer to this is to drop the
    field and write the file anyway.
    """


# --- the type of a field ----------------------------------------------------
#
# A node is a `str` (a scalar type name), a `ListOf`, or a `Struct` — the same
# three shapes the saved file has, so converting between them is direct.


@dataclass(slots=True)
class ListOf:
    """A list, and the one type its items unify to. `None` until an item shows."""

    item: "Node | None" = None


@dataclass(slots=True)
class Struct:
    """An object, and a node per field name seen anywhere in the corpus."""

    fields: dict[str, "Node"] = field(default_factory=dict)


Node = str | ListOf | Struct


def _describe(node: Node | None) -> str:
    """A node in one line, for an error message."""
    if node is None:
        return "unobserved"

    if isinstance(node, ListOf):
        return f"list<{_describe(node.item)}>"

    if isinstance(node, Struct):
        return f"struct<{', '.join(sorted(node.fields))}>"

    return node


def _observe(value: object, known: Node | None, path: str) -> Node:
    """Widen `known` so it also holds `value`, or raise if it cannot.

    `None` is not a type — a null tells you a field can be missing, which
    Parquet allows for every column anyway, and nothing about what it holds when
    it is present. So it constrains nothing and returns `known` untouched.
    """
    if value is None:
        return known

    if isinstance(value, dict):
        if known is not None and not isinstance(known, Struct):
            raise SchemaConflict(
                f"{path} is an object here and {_describe(known)} elsewhere in "
                f"the same partition. Arrow holds one type per column."
            )

        node = known if isinstance(known, Struct) else Struct()

        for name, item in value.items():
            node.fields[name] = _observe(item, node.fields.get(name), f"{path}.{name}")

        return node

    if isinstance(value, list):
        if known is not None and not isinstance(known, ListOf):
            raise SchemaConflict(
                f"{path} is an array here and {_describe(known)} elsewhere in "
                f"the same partition. Arrow holds one type per column."
            )

        node = known if isinstance(known, ListOf) else ListOf()

        for item in value:
            node.item = _observe(item, node.item, f"{path}[]")

        return node

    scalar = SCALARS.get(type(value))

    if scalar is None:
        raise SchemaConflict(
            f"{path} is a {type(value).__name__}, which is not something JSON "
            f"produces. The stream should yield only str, bool, int, float, "
            f"list, dict and None."
        )

    if known is None:
        return scalar

    if known != scalar:
        raise SchemaConflict(
            f"{path} is {scalar} here and {_describe(known)} elsewhere in the "
            f"same partition. Neither is coerced into the other — record which "
            f"reports disagree and decide, rather than widening silently."
        )

    return scalar


def _arrow(node: Node | None, path: str) -> pa.DataType:
    """The Arrow type for a node, with unobserved fields resolved to string."""
    if node is None:
        return ARROW_SCALARS[UNOBSERVED]

    if isinstance(node, ListOf):
        return pa.list_(_arrow(node.item, f"{path}[]"))

    if isinstance(node, Struct):
        if not node.fields:
            raise UnwritableSchema(
                f"{path} was an object in every record that had it, and empty "
                f"in all of them. Parquet cannot write a struct with no fields, "
                f"so this needs a decision — most likely dropping the field, "
                f"which is a decision no inference pass gets to make quietly."
            )

        return pa.struct(
            [
                pa.field(name, _arrow(node.fields[name], f"{path}.{name}"))
                for name in sorted(node.fields)
            ]
        )

    return ARROW_SCALARS[node]


# --- the schemas of one partition -------------------------------------------


@dataclass(frozen=True)
class Schemas:
    """One `pa.Schema` per table, frozen before any row is written."""

    tables: dict[str, pa.Schema]

    def __getitem__(self, table: str) -> pa.Schema:
        return self.tables[table]

    def has_column(self, table: str, column: str) -> bool:
        """Whether a table carries a column at all.

        A 2005-era partition may have no `unii` anywhere in it. That is a
        difference to record, not a query that should explode (spec, P2).
        """
        return column in self.tables[table].names


def _pin_pipeline_columns(nodes: dict[str, Node | None], table: str) -> None:
    """Give this table's own columns their declared type, in place.

    Set whether or not the partition filled them, so a table no report happened
    to fill still has its join key. A `report_duplicate` of zero rows is a table
    with no duplicates in it; a `report_duplicate` with no columns is a table
    the next partition's schema will disagree with.
    """
    for name in PIPELINE_COLUMNS[table]:
        declared = COLUMN_TYPES[name]
        observed = nodes.get(name)

        if observed is not None and observed != declared:
            raise SchemaConflict(
                f"{table}.{name} is a column this pipeline writes and should be "
                f"{declared}, but it arrived as {_describe(observed)}. Either "
                f"`split` no longer writes what it says it writes, or openFDA "
                f"now has a source field by that name."
            )

        nodes[name] = declared


def infer(reports: Iterable[dict]) -> Schemas:
    """The union of every field of every row, over the whole stream.

    Runs `split` itself, on its own dimension, so the schema describes the rows
    that will actually be written rather than a parallel guess at their shape.
    The dimension is thrown away with the pass: pass 2 rebuilds it, and each
    block is emitted on its own first sight there.

    Raises:
        SchemaConflict: one field arrived with two irreconcilable types.
        UnwritableSchema: a struct that is empty in every record.
    """
    observed: dict[str, dict[str, Node]] = {table: {} for table in TABLES}
    dimension = OpenfdaDimension()

    for report in reports:
        for table, rows in split(report, dimension).by_table().items():
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


# --- the file ---------------------------------------------------------------


def _to_json(arrow_type: pa.DataType) -> object:
    if pa.types.is_list(arrow_type):
        return [_to_json(arrow_type.value_type)]

    if pa.types.is_struct(arrow_type):
        return {child.name: _to_json(child.type) for child in arrow_type}

    for name, scalar in ARROW_SCALARS.items():
        if arrow_type.equals(scalar):
            return name

    raise UnwritableSchema(f"{arrow_type} has no representation in a schema file.")


def _from_json(node: object, path: str) -> pa.DataType:
    if isinstance(node, list):
        if len(node) != 1:
            raise UnreadableSchema(
                f"{path}: a list type is written as a one-element array naming "
                f"its item type, found {len(node)} elements."
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
        f"{path}: {node!r} is not a type this module writes "
        f"({', '.join(sorted(ARROW_SCALARS))}, an object, or a one-element array)."
    )


def save(path: Path, schemas: Schemas, *, source: dict) -> None:
    """Write the schemas, plus which export they were read from.

    `source` is on the file because of L-006: openFDA re-chunks quarters between
    exports, so a schema is only known to describe the partition of the export it
    was inferred from. A schema file with no export date is a claim with no date
    on it.
    """
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
    """Read back a saved schema. `source` is metadata for a reader, not used here.

    Raises:
        UnreadableSchema: the file is not the shape `save` writes.
    """
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


# --- what the schema refuses --------------------------------------------------


def _is_nested(arrow_type: pa.DataType) -> bool:
    return pa.types.is_struct(arrow_type) or pa.types.is_list(arrow_type)


def _enforce_nested(value: object, arrow_type: pa.DataType, table: str, path: str) -> None:
    """Recurse into structs and lists of structs only.

    A scalar needs no check here — Arrow raises on its own when a str arrives
    for an int64 column. What Arrow does *not* do is complain about a key it has
    no field for, at any depth, which is the whole reason this walk exists. It
    skips lists of scalars, so the openfda block's `list<string>` columns — most
    of the corpus's values — cost nothing.
    """
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
    """Raise if any row carries a field the schema has no column for.

    Checked per batch rather than per row so the column lookup is built once.
    A row *missing* a column is fine and stays fine — every Parquet column is
    nullable, and a field absent from a report is exactly what null means.

    Raises:
        UnknownField: a row has a field the schema does not.
    """
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
