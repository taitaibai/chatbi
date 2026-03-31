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
        if result.row_count == 1 and len(result.columns) == 1:
            return "card"
        if result.row_count <= 1:
            return "table"

        first_column = result.columns[0].lower()
        if "date" in first_column or "day" in first_column:
            return "line"
        if result.row_count <= 6 and len(result.columns) == 2:
            return "pie"
        if len(result.columns) >= 2:
            return "bar"
        return "table"

    def _build_option(self, chart_type: str, result: QueryResult) -> dict:
        if chart_type == "card":
            return {
                "title": {"text": result.columns[0], "left": "center"},
                "series": [{"type": "gauge", "detail": {"formatter": str(result.rows[0][0])}}],
            }
        if chart_type == "line":
            return {
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": [row[0] for row in result.rows]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "smooth": True,
                        "data": [row[1] for row in result.rows],
                    }
                ],
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
            return {
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": [row[0] for row in result.rows]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "data": [row[1] for row in result.rows],
                        "itemStyle": {"borderRadius": [8, 8, 0, 0]},
                    }
                ],
            }
        return {
            "dataset": {
                "source": [result.columns, *result.rows],
            }
        }


visualization_service = VisualizationService()
