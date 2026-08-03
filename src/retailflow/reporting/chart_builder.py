"""Small chart builders for management-report worksheets."""

from xlsxwriter.workbook import Workbook
from xlsxwriter.worksheet import Worksheet


def add_column_chart(
    workbook: Workbook,
    worksheet: Worksheet,
    *,
    sheet_name: str,
    first_data_row: int,
    last_data_row: int,
    category_column: int,
    value_column: int,
    title: str,
    position: str,
) -> bool:
    """Add a column chart and return whether a non-empty chart was created."""
    if last_data_row < first_data_row:
        return False
    chart = workbook.add_chart({"type": "column"})
    chart.add_series(
        {
            "name": title,
            "categories": [
                sheet_name,
                first_data_row,
                category_column,
                last_data_row,
                category_column,
            ],
            "values": [sheet_name, first_data_row, value_column, last_data_row, value_column],
            "fill": {"color": "#4F81BD"},
            "border": {"color": "#385D8A"},
        }
    )
    chart.set_title({"name": title})
    chart.set_legend({"none": True})
    chart.set_y_axis({"major_gridlines": {"visible": True}})
    chart.set_style(10)
    worksheet.insert_chart(position, chart, {"x_scale": 1.25, "y_scale": 1.1})
    return True
