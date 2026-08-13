"""The union of every record, and what it refuses to guess.

Two properties carry the weight. A type must be the union over all the records
rather than whichever record came first — the habit that cost 89.6% of
`companynumb` (L-005) — so most of these tests hand `infer` records that
disagree and check the result holds both. And a disagreement Arrow cannot hold
must raise instead of widening, because a schema that quietly becomes `string`
is how a corpus loses a distinction nobody notices for a milestone.

The rest is `enforce`, which exists for one measured reason: Arrow drops any key
the schema has no column for and writes the file anyway, at the top level and
inside a struct both.
"""

import json

import pyarrow as pa
import pytest

from hindsight.normalize import TABLES
from hindsight.schema import (
    SchemaConflict,
    UnknownField,
    UnreadableSchema,
    UnwritableSchema,
    enforce,
    infer,
    load,
    save,
)


def report(**overrides) -> dict:
    return {"safetyreportid": "1"} | overrides


def report_schema(*reports) -> pa.Schema:
    """The inferred `report` schema for a handful of records."""
    return infer(iter(reports))["report"]


def column(schema: pa.Schema, name: str) -> pa.DataType:
    return schema.field(name).type


# --- the union, not the first record ----------------------------------------


def test_a_field_only_the_last_record_has_is_still_a_column():
    """The L-005 rule at schema level: `companynumb` is on 87.6% of reports, so
    a schema built from the first record is a schema that drops it from all of
    them without changing a row count."""
    schema = report_schema(report(), report(), report(companynumb="C1"))

    assert column(schema, "companynumb") == pa.string()


def test_a_struct_takes_the_union_of_the_fields_across_records():
    """`primarysource` carries a literature reference on a minority of reports.
    Unifying to the first record's shape loses the field for every record that
    had it."""
    schema = report_schema(
        report(primarysource={"qualification": "1"}),
        report(primarysource={"reportercountry": "US"}),
    )

    assert column(schema, "primarysource") == pa.struct(
        [("qualification", pa.string()), ("reportercountry", pa.string())]
    )


def test_nested_structs_unify_at_every_depth():
    schema = report_schema(
        report(sender={"a": {"x": "1"}}),
        report(sender={"a": {"y": "2"}}),
    )

    assert column(schema, "sender") == pa.struct(
        [("a", pa.struct([("x", pa.string()), ("y", pa.string())]))]
    )


def test_a_null_says_nothing_about_the_type():
    """Every Parquet column is nullable, so a null is not evidence. Letting it
    win would type a field by whichever record happened to omit it."""
    schema = report_schema(report(occurcountry=None), report(occurcountry="US"))

    assert column(schema, "occurcountry") == pa.string()


def test_a_field_that_is_null_in_every_record_becomes_a_string():
    """String is the one resolution that cannot lose information later: the
    values are unknown, and a wrong integer column would reject them."""
    schema = report_schema(report(occurcountry=None))

    assert column(schema, "occurcountry") == pa.string()


def test_an_empty_list_in_every_record_becomes_a_list_of_strings():
    schema = report_schema(report(tags=[]))

    assert column(schema, "tags") == pa.list_(pa.string())


def test_a_list_takes_its_item_type_from_any_record_that_has_one():
    schema = report_schema(report(tags=[]), report(tags=["x"]))

    assert column(schema, "tags") == pa.list_(pa.string())


def test_field_names_are_sorted_so_two_schema_files_can_be_diffed():
    """M1's drift check is a diff between two of these files. In insertion order
    the diff shows which record arrived first, which is not a fact about the
    data."""
    schema = report_schema(report(zulu="1", alpha="2"))

    assert schema.names == sorted(schema.names)


def test_every_table_gets_a_schema_even_when_no_record_fills_it():
    """A partition where no report has a duplicate still has the table, and the
    table still has its join key. Zero rows is a fact about the partition; zero
    columns is a schema the next partition disagrees with, and 1,767 of them
    have to agree for the corpus to be queryable as one thing."""
    schemas = infer(iter([report()]))

    assert set(schemas.tables) == set(TABLES)
    assert schemas["report_duplicate"].names == ["safetyreportid", "seq"]


# --- what it refuses to reconcile -------------------------------------------


def test_an_object_here_and_an_array_there_raises():
    """This is the error that found `reportduplicate` — 1,857 objects against
    1,096 arrays in one partition, which is now a table of its own. The next
    field to do it is a modelling decision too, and inference does not get to
    settle it by picking one shape."""
    with pytest.raises(SchemaConflict, match="report.sender"):
        report_schema(report(sender={"sendertype": "2"}), report(sender=[]))


def test_two_scalar_types_in_one_field_raise():
    with pytest.raises(SchemaConflict, match="int64 here and string"):
        report_schema(report(serious="1"), report(serious=2))


def test_int_and_double_are_not_quietly_widened():
    """The widening every library does by default. This project's schema bugs
    all came from a quiet resolution, so the one that loses precision on
    9,007,199,254,740,993 is not applied without someone deciding to."""
    with pytest.raises(SchemaConflict):
        report_schema(report(n=1), report(n=1.5))


def test_true_is_a_bool_and_not_an_int():
    """`bool` subclasses `int` in Python, so an isinstance chain types every
    True as int64 and then raises on the first real integer."""
    schema = report_schema(report(flag=True))

    assert column(schema, "flag") == pa.bool_()


def test_a_struct_that_is_empty_in_every_record_raises_rather_than_being_dropped():
    """Parquet cannot write a struct with no child fields. Dropping the column
    would be the convenient answer and it is a data-loss decision, so it is
    raised to a human instead."""
    with pytest.raises(UnwritableSchema, match="report.summary"):
        report_schema(report(summary={}))


# --- the columns the pipeline writes itself ---------------------------------


def test_seq_stays_an_integer_even_when_it_is_null_in_every_row():
    """A partition where every duplicate arrived as a bare object has a null
    `seq` on every row. Inferring it would give `string` there and `int64` in
    the next partition, and a column whose type depends on the partition is the
    drift this file exists to catch."""
    schemas = infer(iter([report(reportduplicate={"duplicatenumb": "D1"})]))

    assert column(schemas["report_duplicate"], "seq") == pa.int64()


def test_a_pipeline_column_that_disagrees_with_its_declared_type_raises():
    schemas = infer(iter([report(patient={"drug": [{}]})]))

    assert column(schemas["report_drug"], "seq") == pa.int64()
    assert column(schemas["report_drug"], "openfda_key") == pa.string()


def test_openfda_key_is_not_invented_for_tables_that_have_no_such_column():
    schema = report_schema(report())

    assert "openfda_key" not in schema.names


# --- the file ---------------------------------------------------------------


def test_a_saved_schema_loads_back_identical(tmp_path):
    """The file is the contract pass 2 writes against. If it does not round
    trip, the committed artifact and the schema in memory are two different
    things."""
    schemas = infer(
        iter(
            [
                report(
                    primarysource={"qualification": "1"},
                    patient={"drug": [{"openfda": {"unii": ["X"]}}], "reaction": [{}]},
                )
            ]
        )
    )
    path = tmp_path / "schema.json"

    save(path, schemas, source={"partition": "2025q1/0001-of-0028"})
    loaded = load(path)

    assert all(loaded[table].equals(schemas[table]) for table in TABLES)


def test_the_file_reads_like_a_record_with_types_where_the_values_were(tmp_path):
    """A reviewer has to be able to read it. A scalar is its type name, an
    object is an object, and a list is a one-element array of its item type."""
    path = tmp_path / "schema.json"
    schemas = infer(iter([report(primarysource={"qualification": "1"}, tags=["x"])]))

    save(path, schemas, source={})

    assert json.loads(path.read_text())["tables"]["report"] == {
        "primarysource": {"qualification": "string"},
        "safetyreportid": "string",
        "tags": ["string"],
    }


def test_the_export_the_schema_came_from_is_on_the_file(tmp_path):
    """openFDA re-chunks quarters between exports (L-006), so a schema only
    describes the partition of the export it was read from."""
    path = tmp_path / "schema.json"

    save(path, infer(iter([report()])), source={"export_date": "2026-08-10"})

    assert json.loads(path.read_text())["source"]["export_date"] == "2026-08-10"


def test_a_schema_file_missing_a_table_is_refused(tmp_path):
    """Silently defaulting it would write that table against an empty schema and
    drop every column it has."""
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"source": {}, "tables": {"report": {}}}))

    with pytest.raises(UnreadableSchema, match="report_drug"):
        load(path)


def test_a_type_name_the_writer_never_writes_is_refused(tmp_path):
    path = tmp_path / "schema.json"
    tables = {table: {} for table in TABLES}
    tables["report"] = {"safetyreportid": "varchar"}
    path.write_text(json.dumps({"source": {}, "tables": tables}))

    with pytest.raises(UnreadableSchema, match="varchar"):
        load(path)


def test_a_list_type_with_two_item_types_is_refused(tmp_path):
    path = tmp_path / "schema.json"
    tables = {table: {} for table in TABLES}
    tables["report"] = {"tags": ["string", "int64"]}
    path.write_text(json.dumps({"source": {}, "tables": tables}))

    with pytest.raises(UnreadableSchema, match="one-element array"):
        load(path)


# --- enforce: the field Arrow would have dropped ----------------------------


SCHEMA = pa.schema(
    [
        pa.field("safetyreportid", pa.string()),
        pa.field("primarysource", pa.struct([("qualification", pa.string())])),
        pa.field("tags", pa.list_(pa.string())),
        pa.field("entries", pa.list_(pa.struct([("numb", pa.string())]))),
    ]
)


def test_a_row_matching_the_schema_passes():
    enforce([{"safetyreportid": "1", "tags": ["x"]}], SCHEMA, "report")


def test_a_missing_column_is_not_an_error():
    """Absent is null, and every column is nullable. Requiring all of them would
    reject the 87.6%-coverage reality of this corpus."""
    enforce([{}], SCHEMA, "report")


def test_a_field_the_schema_has_no_column_for_raises():
    """Measured: `Table.from_pylist` drops it and writes valid Parquet with a
    matching row count. Across 1,767 partitions that is a field that vanishes
    from the corpus with nothing in the output to say so."""
    with pytest.raises(UnknownField, match=r"\['ghost'\]"):
        enforce([{"safetyreportid": "1", "ghost": "x"}], SCHEMA, "report")


def test_the_message_names_the_table_because_the_row_is_one_of_millions():
    with pytest.raises(UnknownField, match="report_drug"):
        enforce([{"ghost": "x"}], SCHEMA, "report_drug")


def test_an_unknown_field_inside_a_struct_raises_too():
    """Arrow drops these just as quietly, one level down, where a column-name
    check would never look."""
    with pytest.raises(UnknownField, match="primarysource"):
        enforce([{"primarysource": {"qualification": "1", "ghost": "x"}}], SCHEMA, "report")


def test_an_unknown_field_inside_a_list_of_structs_raises_and_names_the_position():
    with pytest.raises(UnknownField, match=r"entries\[1\]"):
        enforce([{"entries": [{"numb": "1"}, {"ghost": "x"}]}], SCHEMA, "report")


def test_a_null_where_a_struct_belongs_is_not_a_missing_field():
    enforce([{"primarysource": None, "entries": [None]}], SCHEMA, "report")
