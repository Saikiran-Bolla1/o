from .status import get_case_status
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

def get_group_status(children):
    priority = {"ERROR": 3, "FAIL": 2, "PASS": 1, "INFO": 0, "NONE": 0}
    group_status = "NONE"
    for child in children:
        status = child.get("status", "NONE")
        if child.get("category") == "GROUP":
            status = get_group_status(child.get("children", []))
            child["status"] = status
        if priority.get(status, 0) > priority.get(group_status, 0):
            group_status = status
    return group_status

def get_table_status(table):
    """
    If the table has a column named 'result', check only that column.
    - If any 'result' is 'FAIL', status is 'FAIL'.
    - If any 'result' is 'PASS', status is 'PASS'.
    - If all 'result' are 'NONE' (or no pass/fail), status is 'NONE'.
    Also: sorts the table rows as FAIL > PASS > NONE > others.
    Works even if column_header or row_header are missing.
    """
    result_idx = None
    headers = table.get("column_header", [])
    if headers:
        for idx, h in enumerate(headers):
            if h.strip().lower() == "result":
                result_idx = idx
                break
    if result_idx is not None:
        priority = {'FAIL': 0, 'PASS': 1, 'NONE': 2}
        data = table.get("data", [])
        data.sort(key=lambda row: priority.get(str(row[result_idx]).strip().upper(), 3))
        found = False
        has_pass = False
        for row in data:
            if len(row) > result_idx:
                val = row[result_idx]
                found = True
                if isinstance(val, str):
                    v = val.strip().upper()
                    if v == "FAIL":
                        return "FAIL"
                    if v == "PASS":
                        has_pass = True
        if found and has_pass:
            return "PASS"
        if found:
            return "NONE"
        return "NONE"
    # Fallback: any cell FAIL, any cell PASS, else NONE
    found = False
    has_pass = False
    for row in table.get("data", []):
        for cell in row:
            if isinstance(cell, str):
                found = True
                v = cell.strip().upper()
                if v == "FAIL":
                    return "FAIL"
                if v == "PASS":
                    has_pass = True
    if found and has_pass:
        return "PASS"
    if found:
        return "NONE"
    return "NONE"

def _normalize_chart_input(input_obj: Any) -> Dict[str, Any]:
    """
    Accept multiple input forms and convert to a chart dict compatible with the frontend:
      - [rec["Sig1"], rec["Sig2"]] where each item has .name, .x, .y, .data
      - rec.values() -> list of objects with .name, .x, .y, .data
      - [[(x0,y0),...], [(x0,y0),...]] -> each inner list is one signal's samples
    Output dict:
      {
        "name": "Signals",
        "legend": [...],
        "x": [...],
        "y": { legend[i]: y_i, ... },
        "xlabel": "Time (s)",
        "ylabel": "Value"
      }
    """
    # Case 1: list/tuple of views or sample-pairs
    if isinstance(input_obj, (list, tuple)):
        items = list(input_obj)
        if not items:
            return {"name": "Signals", "legend": [], "x": [], "y": {}}
        # Duck-typing for view-like objects
        if hasattr(items[0], "x") and hasattr(items[0], "y"):
            # Use the first item's x as the common X axis
            x = list(map(float, getattr(items[0], "x")))
            legend = []
            y_map: Dict[str, List[float]] = {}
            for it in items:
                name = getattr(it, "name", None) or f"Sig{len(legend)+1}"
                legend.append(name)
                y_map[name] = list(map(float, getattr(it, "y")))
            return {
                "name": "Signals",
                "legend": legend,
                "x": x,
                "y": y_map,
                "xlabel": "Time (s)",
                "ylabel": "Value",
            }
        # Otherwise, assume list of list of (x,y) pairs
        elif isinstance(items[0], (list, tuple)) and items and items[0] and isinstance(items[0][0], (list, tuple)):
            sig_pairs: List[List[Tuple[float, float]]] = items  # type: ignore
            x = [float(p[0]) for p in sig_pairs[0]]
            legend = [f"Sig{i+1}" for i in range(len(sig_pairs))]
            y_map = {legend[i]: [float(p[1]) for p in sig_pairs[i]] for i in range(len(sig_pairs))}
            return {
                "name": "Signals",
                "legend": legend,
                "x": x,
                "y": y_map,
                "xlabel": "Time (s)",
                "ylabel": "Value",
            }
    # If already a dict in chart format, return as-is
    if isinstance(input_obj, dict):
        return input_obj
    # Fallback empty chart
    return {"name": "Signals", "legend": [], "x": [], "y": {}}

class TestReport:
    project = None

    @classmethod
    def set_project(cls, project_name):
        cls.project = project_name

    def __init__(self, name, goal=None, requirements=None, dut=None):
        self.name = name
        self.goal = goal
        self.requirements = requirements or []
        self.lines = []
        self.tables = []
        self.charts = []
        self.status = get_case_status(self.lines)
        self.project = TestReport.project
        self._group_stack = []
        self.dut = dut or {}
        self.steps = []  # Optional: keep if other code references it

    @contextmanager
    def start_group(self, title, comment=None):
        group = {
            "category": "GROUP",
            "title": title,
            "comment": comment,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "children": [],
            "status": "NONE"
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(group)
        else:
            self.lines.append(group)
        self._group_stack.append(group)
        try:
            yield
        finally:
            self._group_stack.pop()
            group["status"] = get_group_status(group["children"])
            self.status = get_case_status(self.lines)

    def add_step(self, status, comment):
        step = {
            "category": "STEP",
            "status": status,
            "comment": comment,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(step)
        else:
            self.lines.append(step)
        self.status = get_case_status(self.lines)

    def add_table(self, name, data, column_header=None, row_header=None):
        """
        Add a table by specifying arguments directly.
        - name (str): Name of the table.
        - data (list of lists): Table data (rows).
        - column_header (list, optional): List of column header strings.
        - row_header (list, optional): List of row header strings.
        All arguments except 'name' and 'data' are optional.
        """
        idx = len(self.tables)
        table_dict = {
            "name": name,
            "data": data
        }
        if column_header is not None:
            table_dict["column_header"] = column_header
        if row_header is not None:
            table_dict["row_header"] = row_header
        self.tables.append(table_dict)
        table_status = get_table_status(table_dict)
        table_entry = {
            "category": "TABLE",
            "status": table_status,
            "comment": f"Table: {name or f'Table {idx+1}'}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "table_idx": idx
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(table_entry)
        else:
            self.lines.append(table_entry)
        self.status = get_case_status(self.lines)

    def add_chart(self, chart):
        """
        Add a chart. Accepted inputs:
          - A ready chart dict with keys: x, y (array or dict), legend (optional), name (optional)
          - A list like [rec["Sig1"], rec["Sig2"]] where each item has .name, .x, .y, .data
          - rec.values() from RecorderResult
          - A list of signals as pairs: [[(x0,y0),...], [(x0,y0),...]]
        """
        normalized = _normalize_chart_input(chart)
        idx = len(self.charts)
        self.charts.append(normalized)
        chart_entry = {
            "category": "CHART",
            "status": "NONE",
            "comment": f"Chart: {normalized.get('name', f'Chart {idx+1}')}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "chart_idx": idx
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(chart_entry)
        else:
            self.lines.append(chart_entry)
        self.status = get_case_status(self.lines)

    def condition(self, cond: bool, description: str, comment: str = ""):
        status = "PASS" if cond else "FAIL"
        msg = description
        if comment:
            msg += f" | Comment: {comment}"
        self.add_step(status, msg)

    def add_diagnostic_tx_rx_group(self, name, tx_bytes, rx_bytes, expected, status):
        now = datetime.now().strftime("%H:%M:%S")
        diagnostic = {
            "category": "DIAGNOSTIC",
            "timestamp": now,
            "tx": {"raw": tx_bytes},
            "rx": {"raw": rx_bytes},
            "expected": {"response": expected},
            "status": status
        }
        group = {
            "category": "GROUP",
            "title": f"send diagnostic request {name}",
            "timestamp": now,
            "status": status,
            "children": [diagnostic]
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(group)
        else:
            self.lines.append(group)
        self.status = get_case_status(self.lines)

    def to_dict(self):
        from .status import get_case_status
        self.status = get_case_status(self.lines)
        res = {
            "name": self.name,
            "goal": self.goal,
            "requirements": self.requirements,
            "lines": self.lines,
            "tables": self.tables,
            "charts": self.charts,
            "status": self.status,
            "project": self.project,
            "index": getattr(self, "index", None),
            "dut": self.dut,
        }
        return res
