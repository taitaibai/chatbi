from __future__ import annotations

import sqlglot
from sqlglot import exp

from config.settings import settings


class SQLUnsafeError(ValueError):
    pass


class SecurityChecker:
    FORBIDDEN_EXPRESSIONS = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.Command,
    )

    def validate(self, sql: str) -> bool:
        try:
            tree = sqlglot.parse_one(sql)
        except sqlglot.errors.ParseError as exc:
            raise SQLUnsafeError(f"SQL parse failed: {exc}") from exc

        if not isinstance(tree, exp.Select):
            raise SQLUnsafeError("Only SELECT statements are allowed")

        if ";" in sql.strip().rstrip(";"):
            raise SQLUnsafeError("Multiple SQL statements are not allowed")

        for node in tree.walk():
            if isinstance(node, self.FORBIDDEN_EXPRESSIONS):
                raise SQLUnsafeError(f"Forbidden SQL expression detected: {node.key}")
            if isinstance(node, exp.Table):
                table_name = node.name
                if table_name and table_name not in settings.allowed_tables_set:
                    raise SQLUnsafeError(f"Table not allowed: {table_name}")
        return True


security_checker = SecurityChecker()
