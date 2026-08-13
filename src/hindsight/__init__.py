"""Hindsight — point-in-time signal detection over FDA FAERS.

Modules are added one task at a time (see .specs/features/m0-walking-skeleton/tasks.md):

    manifest   T4   resolve a partition id to a pinned URL + export date
    fetch      T5   download it, verify SHA-256, atomically place it
    stream     T6   yield reports one at a time from inside the zip
    schema     T9   pass 1 — union the types across every record
    normalize  T7/T8  hash the openfda block, split a report into rows
    write      T9   pass 2 — Parquet row groups against the frozen schema
    roundtrip  T10  rebuild the source JSON from the tables (the proof)
    cli        T5+  wire the above into one command
"""

__version__ = "0.1.0"
