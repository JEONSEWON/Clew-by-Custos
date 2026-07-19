"""src/clew/report - waste report renderer."""

from clew.report._model import WasteDetail
from clew.report.json_report import render_json
from clew.report.markdown import render_markdown

__all__ = ["WasteDetail", "render_markdown", "render_json"]
