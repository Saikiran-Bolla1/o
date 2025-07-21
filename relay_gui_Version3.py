import sys
import csv
import json
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QTextEdit, QMessageBox, QScrollArea
)
from PyQt5.QtCore import Qt

GROUPS_PER_PAGE = 12
FAULT_TYPES = ["OpenLoad", "Common", "UBat", "GND"]

class RelayControl(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Numato Relay Controller - Paginated Groups")
        self.resize(1100, 750)
        self.groups = []
        self.current_page = 0
        self.switch_states = {}  # {(DeviceID, PinNo): value}
        self.fault_map = {}      # Loaded from JSON

        main_layout = QVBoxLayout(self)

        # Navigation Layout
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("Previous")
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.next_page)
        self.page_label = QLabel("Page 1")
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.next_btn)
        main_layout.addLayout(nav_layout)

        # Load group names and fault mapping
        file_layout = QHBoxLayout()
        self.load_groups_btn = QPushButton("Load Group Names")
        self.load_groups_btn.clicked.connect(self.load_groups)
        file_layout.addWidget(self.load_groups_btn)
        self.load_faults_btn = QPushButton("Load Fault JSON")
        self.load_faults_btn.clicked.connect(self.load_fault_json)
        file_layout.addWidget(self.load_faults_btn)
        main_layout.addLayout(file_layout)

        # Groups display area with scroll
        self.scroll_area = QScrollArea()
        self.groups_widget = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_widget)
        self.groups_widget.setLayout(self.groups_layout)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.groups_widget)
        main_layout.addWidget(self.scroll_area, stretch=1)

        # Console output
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        main_layout.addWidget(QLabel("Console Output:"))
        main_layout.addWidget(self.console, stretch=1)

        self.set_default_groups()
        self.update_page()

    def set_default_groups(self):
        self.groups = [f"Group {i+1}" for i in range(108)]

    def load_groups(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Group Name File", "", "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)")
        if file_name:
            try:
                with open(file_name, newline='', encoding='utf-8') as f:
                    if file_name.endswith('.csv'):
                        reader = csv.reader(f)
                        self.groups = [row[0] for row in reader if row]
                    else:
                        self.groups = [line.strip() for line in f if line.strip()]
                if len(self.groups) < 108:
                    self.groups += [f"Group {i+1}" for i in range(len(self.groups), 108)]
                elif len(self.groups) > 108:
                    self.groups = self.groups[:108]
                self.console.append(f"Loaded group names from {file_name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load group names: {e}")
        self.current_page = 0
        self.update_page()

    def load_fault_json(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Fault Map JSON", "", "JSON Files (*.json);;All Files (*)")
        if file_name:
            try:
                with open(file_name, 'r', encoding='utf-8') as f:
                    self.fault_map = json.load(f)
                self.console.append(f"Loaded fault mapping from {file_name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load JSON: {e}")

    def update_page(self):
        # Clear previous layout
        for i in reversed(range(self.groups_layout.count())):
            widget = self.groups_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        start = self.current_page * GROUPS_PER_PAGE
        end = min(start + GROUPS_PER_PAGE, len(self.groups))

        self.button_refs = {}

        for idx in range(start, end):
            group_name = self.groups[idx]
            group_row = QHBoxLayout()
            label = QLabel(group_name)
            label.setFixedWidth(220)
            group_row.addWidget(label)

            # JSON key: Line_01, Line_02, ..., Line_108
            line_key = f"Line_{idx+1:02d}"
            fault_entry = self.fault_map.get(line_key, {})

            for action_idx, fault in enumerate(FAULT_TYPES):
                btn = QPushButton(fault)
                btn.setCheckable(True)
                btn.setAutoExclusive(False)

                entry = fault_entry.get(fault)
                if entry:
                    device = entry.get('DeviceID')
                    pin = entry.get('PinNo')
                else:
                    device, pin = None, None

                state = self.getswitch(device, pin) if device is not None and pin is not None else 0
                btn.setChecked(bool(state))
                self.set_style(btn, state)
                btn.setEnabled(device is not None and pin is not None)

                btn.clicked.connect(self.make_toggle_callback(idx, fault, btn))
                self.button_refs[(idx, action_idx)] = btn
                group_row.addWidget(btn)

            container = QWidget()
            container.setLayout(group_row)
            self.groups_layout.addWidget(container)

        self.page_label.setText(f"Page {self.current_page + 1} / {((len(self.groups) - 1) // GROUPS_PER_PAGE) + 1}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(end < len(self.groups))

    def make_toggle_callback(self, group_idx, fault_name, btn):
        # This binds the current values for signal/slot
        return lambda checked: self.toggle_switch(group_idx, fault_name, btn)

    def set_style(self, btn, state):
        if state:
            btn.setStyleSheet("background-color: lightgreen")
        else:
            btn.setStyleSheet("background-color: lightgray")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_page()

    def next_page(self):
        if (self.current_page + 1) * GROUPS_PER_PAGE < len(self.groups):
            self.current_page += 1
            self.update_page()

    def toggle_switch(self, group_idx, fault_name, btn):
        line_key = f"Line_{group_idx+1:02d}"
        entry = self.fault_map.get(line_key, {}).get(fault_name)
        if not entry:
            self.console.append(f"No mapping for {line_key} - {fault_name}")
            return
        device = entry.get('DeviceID')
        pin = entry.get('PinNo')
        curr_state = self.getswitch(device, pin)
        new_state = 0 if curr_state else 1
        self.setswitch(device, pin, new_state)
        btn.setChecked(bool(new_state))
        self.set_style(btn, new_state)

    def setswitch(self, idevice, ipin, new_state):
        # Store state and log to console (replace with serial logic as needed)
        if idevice is None or ipin is None:
            self.console.append(f"setswitch(None, None, {new_state}) [no-op]")
            return
        self.switch_states[(idevice, ipin)] = new_state
        self.console.append(f"setswitch(DeviceID={idevice}, PinNo={ipin}, value={new_state})")

    def getswitch(self, idevice, ipin):
        if idevice is None or ipin is None:
            return 0
        return self.switch_states.get((idevice, ipin), 0)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RelayControl()
    window.show()
    sys.exit(app.exec_())
