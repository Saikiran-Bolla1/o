import sys
import csv
import json
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QTextEdit, QMessageBox, QScrollArea
)
from PyQt5.QtCore import Qt

GROUPS_PER_PAGE = 12
ACTION_TYPES = ["OpenLoad", "ShortToUBat", "ShortToGND", "ShortToPin"]

class RelayControl(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Numato Relay Controller - Paginated Groups")
        self.resize(1200, 800)
        self.groups = []
        self.group_line_keys = []
        self.current_page = 0
        self.switch_states = {}  # {(DeviceID, PinNo): value}
        self.fault_map = {}
        self.shorttopin_selected = []  # List of group indexes with active ShortToPin (max 2)

        main_layout = QVBoxLayout(self)
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

        file_layout = QHBoxLayout()
        self.load_groups_btn = QPushButton("Load Group Names")
        self.load_groups_btn.clicked.connect(self.load_groups)
        file_layout.addWidget(self.load_groups_btn)
        self.load_faults_btn = QPushButton("Load Fault JSON")
        self.load_faults_btn.clicked.connect(self.load_fault_json)
        file_layout.addWidget(self.load_faults_btn)
        main_layout.addLayout(file_layout)

        self.scroll_area = QScrollArea()
        self.groups_widget = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_widget)
        self.groups_widget.setLayout(self.groups_layout)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.groups_widget)
        main_layout.addWidget(self.scroll_area, stretch=1)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        main_layout.addWidget(QLabel("Console Output:"))
        main_layout.addWidget(self.console, stretch=1)

        self.set_default_groups()
        self.update_page()

    def set_default_groups(self):
        self.groups = [f"Group {i+1}" for i in range(108)]
        self.group_line_keys = [f"Line_{i+1:02d}" for i in range(108)]

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
        self.group_line_keys = [f"Line_{i+1:02d}" for i in range(len(self.groups))]
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
        for i in reversed(range(self.groups_layout.count())):
            widget = self.groups_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        start = self.current_page * GROUPS_PER_PAGE
        end = min(start + GROUPS_PER_PAGE, len(self.groups))
        self.button_refs = {}

        for idx in range(start, end):
            group_name = self.groups[idx]
            line_key = self.group_line_keys[idx]
            group_row = QHBoxLayout()
            label = QLabel(f"{group_name} - {line_key}")
            label.setFixedWidth(300)
            group_row.addWidget(label)

            fault_entry = self.fault_map.get(line_key, {})
            for action in ACTION_TYPES:
                btn = QPushButton(action)
                btn.setCheckable(True)
                btn.setAutoExclusive(False)
                enabled = (
                    (action == "OpenLoad" and "OpenLoad" in fault_entry) or
                    (action == "ShortToUBat" and "Common" in fault_entry and "UBat" in fault_entry) or
                    (action == "ShortToGND" and "Common" in fault_entry and "GND" in fault_entry) or
                    (action == "ShortToPin" and "Common" in fault_entry)
                )
                btn.setEnabled(enabled)
                btn.setChecked(self.is_fault_active(idx, action))
                self.set_style(btn, btn.isChecked())
                btn.clicked.connect(self.make_toggle_callback(idx, action, btn))
                self.button_refs[(idx, action)] = btn
                group_row.addWidget(btn)
            container = QWidget()
            container.setLayout(group_row)
            self.groups_layout.addWidget(container)

        self.page_label.setText(f"Page {self.current_page + 1} / {((len(self.groups) - 1) // GROUPS_PER_PAGE) + 1}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(end < len(self.groups))

    def make_toggle_callback(self, group_idx, action, btn):
        return lambda checked: self.toggle_switch(group_idx, action, btn)

    def set_style(self, btn, state):
        btn.setStyleSheet("background-color: lightgreen" if state else "background-color: lightgray")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_page()

    def next_page(self):
        if (self.current_page + 1) * GROUPS_PER_PAGE < len(self.groups):
            self.current_page += 1
            self.update_page()

    def deactivate_all_faults_in_group(self, group_idx):
        line_key = self.group_line_keys[group_idx]
        fault_entry = self.fault_map.get(line_key, {})
        # OpenLoad
        entry = fault_entry.get("OpenLoad")
        if entry:
            self.setswitch(entry.get('DeviceID'), entry.get('PinNo'), 0)
        # ShortToUBat
        entry1 = fault_entry.get("Common")
        entry2 = fault_entry.get("UBat")
        if entry1 and entry2:
            self.setswitch(entry1.get('DeviceID'), entry1.get('PinNo'), 0)
            self.setswitch(entry2.get('DeviceID'), entry2.get('PinNo'), 0)
        # ShortToGND
        entry1 = fault_entry.get("Common")
        entry2 = fault_entry.get("GND")
        if entry1 and entry2:
            self.setswitch(entry1.get('DeviceID'), entry1.get('PinNo'), 0)
            self.setswitch(entry2.get('DeviceID'), entry2.get('PinNo'), 0)
        # ShortToPin
        if group_idx in self.shorttopin_selected:
            src_entry = fault_entry.get("Common")
            if src_entry:
                self.setswitch(src_entry.get('DeviceID'), src_entry.get('PinNo'), 0)
            self.shorttopin_selected.remove(group_idx)

    def is_fault_active(self, group_idx, action):
        line_key = self.group_line_keys[group_idx]
        fault_entry = self.fault_map.get(line_key, {})
        if action == "OpenLoad":
            entry = fault_entry.get("OpenLoad")
            if entry:
                return self.getswitch(entry.get('DeviceID'), entry.get('PinNo')) == 1
        elif action == "ShortToUBat":
            entry1 = fault_entry.get("Common")
            entry2 = fault_entry.get("UBat")
            if entry1 and entry2:
                return self.getswitch(entry1.get('DeviceID'), entry1.get('PinNo')) == 1 and \
                       self.getswitch(entry2.get('DeviceID'), entry2.get('PinNo')) == 1
        elif action == "ShortToGND":
            entry1 = fault_entry.get("Common")
            entry2 = fault_entry.get("GND")
            if entry1 and entry2:
                return self.getswitch(entry1.get('DeviceID'), entry1.get('PinNo')) == 1 and \
                       self.getswitch(entry2.get('DeviceID'), entry2.get('PinNo')) == 1
        elif action == "ShortToPin":
            return group_idx in self.shorttopin_selected
        return False

    def toggle_switch(self, group_idx, action, btn):
        if action == "ShortToPin":
            # Toggle logic for ShortToPin: Only allow up to 2 groups active at once
            if group_idx in self.shorttopin_selected:
                # Deactivate this group's Common pin
                line_key = self.group_line_keys[group_idx]
                src_entry = self.fault_map.get(line_key, {}).get("Common")
                if src_entry:
                    self.setswitch(src_entry.get('DeviceID'), src_entry.get('PinNo'), 0)
                self.shorttopin_selected.remove(group_idx)
            else:
                if len(self.shorttopin_selected) < 2:
                    # Activate this group's Common pin
                    line_key = self.group_line_keys[group_idx]
                    src_entry = self.fault_map.get(line_key, {}).get("Common")
                    if src_entry:
                        self.setswitch(src_entry.get('DeviceID'), src_entry.get('PinNo'), 1)
                    self.shorttopin_selected.append(group_idx)
                # If already 2 active, do nothing (ignore more)
        else:
            # Deselect all other faults in this group first
            self.deactivate_all_faults_in_group(group_idx)
            line_key = self.group_line_keys[group_idx]
            fault_entry = self.fault_map.get(line_key, {})
            if action == "OpenLoad":
                entry = fault_entry.get("OpenLoad", {})
                device, pin = entry.get('DeviceID'), entry.get('PinNo')
                self.setswitch(device, pin, 1)
            elif action == "ShortToUBat":
                entry1 = fault_entry.get("Common", {})
                entry2 = fault_entry.get("UBat", {})
                dev1, pin1 = entry1.get('DeviceID'), entry1.get('PinNo')
                dev2, pin2 = entry2.get('DeviceID'), entry2.get('PinNo')
                self.setswitch(dev1, pin1, 1)
                self.setswitch(dev2, pin2, 1)
            elif action == "ShortToGND":
                entry1 = fault_entry.get("Common", {})
                entry2 = fault_entry.get("GND", {})
                dev1, pin1 = entry1.get('DeviceID'), entry1.get('PinNo')
                dev2, pin2 = entry2.get('DeviceID'), entry2.get('PinNo')
                self.setswitch(dev1, pin1, 1)
                self.setswitch(dev2, pin2, 1)
        self.update_page()

    def setswitch(self, idevice, ipin, new_state):
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
