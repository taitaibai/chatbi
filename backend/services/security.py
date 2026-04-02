from __future__ import annotations

import sqlglot
from sqlglot import exp

from config.settings import settings


class SQLUnsafeError(ValueError):
    pass


class SecurityChecker:
    MAX_JOIN_COUNT = 3
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

        # Use the AST to detect multiple statements instead of a string search;
        # a raw ";" check would produce false positives when ";" appears inside
        # a string literal (e.g. WHERE remark = 'status; paid').
        if len(sqlglot.parse(sql)) > 1:
            raise SQLUnsafeError("Multiple SQL statements are not allowed")

        if any(isinstance(node, exp.Star) for node in tree.walk()):
            raise SQLUnsafeError("SELECT * is not allowed")

        joins = 0
        for node in tree.walk():
            if isinstance(node, self.FORBIDDEN_EXPRESSIONS):
                raise SQLUnsafeError(f"Forbidden SQL expression detected: {node.key}")
            if isinstance(node, exp.Join):
                joins += 1
            if isinstance(node, exp.Table):
                table_name = node.name
                if table_name and table_name not in settings.allowed_tables_set:
                    raise SQLUnsafeError(f"Table not allowed: {table_name}")

        if joins > self.MAX_JOIN_COUNT:
            raise SQLUnsafeError("Too many joins")

        if self._estimate_rows(tree) > settings.complexity_threshold:
            raise SQLUnsafeError("Query exceeds complexity threshold")

        if not self._has_limit(tree) and not self._is_aggregate_query(tree):
            raise SQLUnsafeError("Non-aggregate queries must include LIMIT")
        return True

    def _estimate_rows(self, tree: exp.Select) -> int:
        table_count = sum(1 for node in tree.walk() if isinstance(node, exp.Table))
        join_count = sum(1 for node in tree.walk() if isinstance(node, exp.Join))
        has_where = tree.args.get("where") is not None
        has_limit = self._has_limit(tree)
        is_aggregate = self._is_aggregate_query(tree)

        estimated_rows = max(table_count, 1) * 1_000_000
        estimated_rows *= max(join_count + 1, 1)

        if has_where:
            estimated_rows //= 10
        if has_limit:
            limit_expression = tree.args["limit"].expression
            if isinstance(limit_expression, exp.Literal) and limit_expression.is_int:
                estimated_rows = min(estimated_rows, int(limit_expression.this))
        if is_aggregate:
            estimated_rows //= 5

        return max(estimated_rows, 1)

    def _has_limit(self, tree: exp.Select) -> bool:
        return tree.args.get("limit") is not None

    def _is_aggregate_query(self, tree: exp.Select) -> bool:
        aggregate_types = (exp.Count, exp.Sum, exp.Min, exp.Max, exp.Avg)
        return any(isinstance(node, aggregate_types) for node in tree.walk()) or (
            tree.args.get("group") is not None
        )


security_checker = SecurityChecker()
