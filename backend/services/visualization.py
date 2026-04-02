from __future__ import annotations

from models import ChartSpec, QueryResult


class VisualizationService:
    def recommend(self, result: QueryResult) -> ChartSpec:
        chart_type = self._pick_chart_type(result)
        return ChartSpec(
            type=chart_type,
            echarts_option=self._build_option(chart_type, result),
        )

    def _pick_chart_type(self, result: QueryResult) -> str:
        if result.total_rows == 1 and len(result.columns) == 1:
            return "card"
        if result.total_rows <= 1:
            return "table"

        first_column = result.columns[0]
        metric_columns = result.columns[1:]
        if first_column.type == "date" or "date" in first_column.name.lower() or "day" in first_column.name.lower():
            return "line"
        if result.total_rows <= 6 and len(metric_columns) == 1:
            return "pie"
        if metric_columns:
            return "bar"
        return "table"

    def _build_option(self, chart_type: str, result: QueryResult) -> dict:
        if chart_type == "card":
            return {
                "title": {"text": result.columns[0].name, "left": "center"},
                "series": [{"type": "gauge", "detail": {"formatter": str(result.rows[0][0])}}],
            }
        if chart_type == "line":
            series = self._build_series(result, preferred_type="line", smooth=True)
            return {
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": [row[0] for row in result.rows]},
                "yAxis": {"type": "value"},
                "legend": {"show": len(series) > 1},
                "series": series,
            }
        if chart_type == "pie":
            return {
                "tooltip": {"trigger": "item"},
                "series": [
                    {
                        "type": "pie",
                        "radius": "65%",
                        "data": [
                            {"name": row[0], "value": row[1]} for row in result.rows
                        ],
                    }
                ],
            }
        if chart_type == "bar":
            series = self._build_series(result, preferred_type="bar")
            return {
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": [row[0] for row in result.rows]},
                "yAxis": {"type": "value"},
                "legend": {"show": len(series) > 1},
                "series": series,
            }
        return {
            "dataset": {
                "source": [
                    [column.name for column in result.columns],
                    *result.rows,
                ],
            }
        }

    def _build_series(
        self, result: QueryResult, preferred_type: str, smooth: bool = False
    ) -> list[dict]:
        series: list[dict] = []
        for index, column in enumerate(result.columns[1:], start=1):
            item = {
                "name": column.name,
                "type": preferred_type,
                "data": [row[index] for row in result.rows],
            }
            if preferred_type == "bar":
                item["itemStyle"] = {"borderRadius": [8, 8, 0, 0]}
            if preferred_type == "line":
                item["smooth"] = smooth
            series.append(item)
        return series


visualization_service = VisualizationService()
