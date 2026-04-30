"""Warehouse session abstraction.

# math: math.tex §VII (Warehouse-native execution model)

Defines the ``WarehouseSession`` Protocol — the seam at which the
categorical pipeline meets a SQL warehouse. The Phase 2 mock
implementation backs it with DuckDB; the Phase 2-sandbox
implementation will back it with ``snowflake.snowpark.Session``.

The Protocol captures only the subset of warehouse capabilities the
pipeline actually depends on: running SQL, registering a vectorised
UDF, reading and writing tabular data. Concrete implementations are
free to be more capable; callers that program against
``WarehouseSession`` remain portable across them.
"""

from collections.abc import Callable, Iterable
from typing import Any, Literal, Protocol, runtime_checkable

import duckdb
import pandas as pd

WriteMode = Literal["overwrite", "append"]
UDF = Callable[..., Any]


@runtime_checkable
class WarehouseSession(Protocol):
    """A warehouse-agnostic session.

    A ``WarehouseSession`` is the single seam between Python-side
    categorical machinery and the warehouse it executes against.
    """

    def sql(self, query: str) -> pd.DataFrame:
        """Run a SQL query and return the result as a DataFrame."""
        ...

    def register_udf(
        self,
        name: str,
        fn: UDF,
        param_types: Iterable[str],
        return_type: str,
    ) -> None:
        """Register a vectorised UDF under ``name``.

        ``fn`` accepts column-wise array arguments (Arrow chunked
        arrays for the DuckDB backend, Pandas Series for Snowpark)
        and returns a column of the same length.
        """
        ...

    def write_table(self, df: pd.DataFrame, name: str, mode: WriteMode = "overwrite") -> None:
        """Materialise ``df`` as a warehouse table."""
        ...

    def read_table(self, name: str) -> pd.DataFrame:
        """Read a warehouse table back as a DataFrame."""
        ...


class DuckDBSession:
    """In-process DuckDB-backed implementation of ``WarehouseSession``.

    Used by the Phase 2 mock-first stack: ``dbt-duckdb`` for feature
    engineering, this session for UDF registration and table I/O. The
    production implementation against ``snowflake.snowpark.Session``
    is a sandbox-time exercise and lives behind the same Protocol.
    """

    def __init__(self, database: str = ":memory:") -> None:
        self._con = duckdb.connect(database=database)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._con

    def sql(self, query: str) -> pd.DataFrame:
        return self._con.execute(query).fetch_df()

    def register_udf(
        self,
        name: str,
        fn: UDF,
        param_types: Iterable[str],
        return_type: str,
    ) -> None:
        self._con.create_function(  # type: ignore[call-overload]
            name,
            fn,
            list(param_types),
            return_type,
            type="arrow",
        )

    def write_table(self, df: pd.DataFrame, name: str, mode: WriteMode = "overwrite") -> None:
        self._con.register("__catins_write_buf", df)
        if mode == "overwrite":
            self._con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM __catins_write_buf")
        else:
            self._con.execute(f"INSERT INTO {name} SELECT * FROM __catins_write_buf")
        self._con.unregister("__catins_write_buf")

    def read_table(self, name: str) -> pd.DataFrame:
        return self._con.execute(f"SELECT * FROM {name}").fetch_df()

    def close(self) -> None:
        self._con.close()
