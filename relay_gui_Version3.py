import sys
import csv
import json
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QTextEdit, QMessageBox, QScrollArea, QComboBox, QDialog, QDialogButtonBox, QFormLayout
)
from PyQt5.QtCore import Qt

GROUPS_PER_PAGE = 12
ACTION_TYPES = ["OpenLoad", "ShortToUBat", "ShortToGND", "ShortToCoil"]

class CoilPinDialog(QDialog):
    def __init__(self, pinlist, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Two Pins for ShortToCoil")
        self.pins = pinlist
        layout = QFormLayout(self)
        self.combo1 = QComboBox()
        self.combo2 = QComboBox()
        self.combo1.addItems(self.pins)
        self.combo2.addItems(self.pins)
        layout.addRow("Pin 1:", self.combo1)
        layout.addRow("Pin 2:", self.combo2)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_selection(self):
        return self.combo1.currentText(), self.combo2.currentText()

class RelayControl(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Numato Relay Controller - Paginated Groups")
        self.resize(1200, 800)
        self.groups = []
        self.group_line_keys = []
        self.current_page = 0
        self.switch_states = {}  # {(DeviceID, PinNo): value}
        self.fault_map = {}      # Loaded from JSON

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
        # By default, create 108 groups
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

            # Build a pin selection list for ShortToCoil
            all_pins = []
            for k, v in fault_entry.items():
                pin_str = f"{k} (Device:{v.get('DeviceID','')},Pin:{v.get('PinNo','')})"
                all_pins.append(pin_str)

            for action_idx, action in enumerate(ACTION_TYPES):
                btn = QPushButton(action)
                btn.setCheckable(True)
                btn.setAutoExclusive(False)

                # OpenLoad: only OpenLoad pin
                # ShortToUBat: both Common and UBat
                # ShortToGND: both Common and GND
                # ShortToCoil: select two pins (from all available)
                enabled = True
                if action == "OpenLoad":
                    enabled = "OpenLoad" in fault_entry
                elif action == "ShortToUBat":
                    enabled = "Common" in fault_entry and "UBat" in fault_entry
                elif action == "ShortToGND":
                    enabled = "Common" in fault_entry and "GND" in fault_entry
                elif action == "ShortToCoil":
                    enabled = len(all_pins) >= 2

                btn.setEnabled(enabled)

                # State logic: button is ON if all relevant pins are ON
                if action == "OpenLoad" and enabled:
                    entry = fault_entry.get("OpenLoad")
                    device, pin = entry.get('DeviceID'), entry.get('PinNo')
                    state = self.getswitch(device, pin)
                elif action == "ShortToUBat" and enabled:
                    entry1 = fault_entry.get("Common")
                    entry2 = fault_entry.get("UBat")
                    state = self.getswitch(entry1.get('DeviceID'), entry1.get('PinNo')) and self.getswitch(entry2.get('DeviceID'), entry2.get('PinNo'))
                elif action == "ShortToGND" and enabled:
                    entry1 = fault_entry.get("Common")
                    entry2 = fault_entry.get("GND")
                    state = self.getswitch(entry1.get('DeviceID'), entry1.get('PinNo')) and self.getswitch(entry2.get('DeviceID'), entry2.get('PinNo'))
                elif action == "ShortToCoil" and enabled:
                    # No way to know; just show as OFF
                    state = 0
                else:
                    state = 0

                btn.setChecked(bool(state))
                self.set_style(btn, state)

                btn.clicked.connect(self.make_toggle_callback(idx, action, btn, all_pins))
                self.button_refs[(idx, action_idx)] = btn
                group_row.addWidget(btn)

            container = QWidget()
            container.setLayout(group_row)
            self.groups_layout.addWidget(container)

        self.page_label.setText(f"Page {self.current_page + 1} / {((len(self.groups) - 1) // GROUPS_PER_PAGE) + 1}")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(end < len(self.groups))

    def make_toggle_callback(self, group_idx, action, btn, all_pins):
        # Binds current values for signal/slot
        return lambda checked: self.toggle_switch(group_idx, action, btn, all_pins)

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

    def toggle_switch(self, group_idx, action, btn, all_pins):
        line_key = self.group_line_keys[group_idx]
        fault_entry = self.fault_map.get(line_key, {})
        # OpenLoad: toggle single pin
        if action == "OpenLoad":
            entry = fault_entry.get("OpenLoad", {})
            device, pin = entry.get('DeviceID'), entry.get('PinNo')
            curr_state = self.getswitch(device, pin)
            new_state = 0 if curr_state else 1
            self.setswitch(device, pin, new_state)
            btn.setChecked(bool(new_state))
            self.set_style(btn, new_state)
        # ShortToUBat: toggle both Common and UBat pins together
        elif action == "ShortToUBat":
            entry1 = fault_entry.get("Common", {})
            entry2 = fault_entry.get("UBat", {})
            dev1, pin1 = entry1.get('DeviceID'), entry1.get('PinNo')
            dev2, pin2 = entry2.get('DeviceID'), entry2.get('PinNo')
            curr_state = self.getswitch(dev1, pin1) and self.getswitch(dev2, pin2)
            new_state = 0 if curr_state else 1
            self.setswitch(dev1, pin1, new_state)
            self.setswitch(dev2, pin2, new_state)
            btn.setChecked(bool(new_state))
            self.set_style(btn, new_state)
        # ShortToGND: toggle both Common and GND pins together
        elif action == "ShortToGND":
            entry1 = fault_entry.get("Common", {})
            entry2 = fault_entry.get("GND", {})
            dev1, pin1 = entry1.get('DeviceID'), entry1.get('PinNo')
            dev2, pin2 = entry2.get('DeviceID'), entry2.get('PinNo')
            curr_state = self.getswitch(dev1, pin1) and self.getswitch(dev2, pin2)
            new_state = 0 if curr_state else 1
            self.setswitch(dev1, pin1, new_state)
            self.setswitch(dev2, pin2, new_state)
            btn.setChecked(bool(new_state))
            self.set_style(btn, new_state)
        # ShortToCoil: show dialog, user selects two pins, then activate both
        elif action == "ShortToCoil":
            if len(all_pins) < 2:
                QMessageBox.warning(self, "Not enough pins", "Not enough pins to perform ShortToCoil.")
                return
            dlg = CoilPinDialog(all_pins, self)
            if dlg.exec_() == QDialog.Accepted:
                sel1, sel2 = dlg.get_selection()
                # Extract pin key from string
                def parse_pin(s):
                    import re
                    m = re.search(r'\(Device:(.*?),Pin:(.*?)\)', s)
                    return (m.group(1).strip(), int(m.group(2).strip())) if m else (None, None)
                dev1, pin1 = parse_pin(sel1)
                dev2, pin2 = parse_pin(sel2)
                if dev1 == dev2 and pin1 == pin2:
                    QMessageBox.warning(self, "Invalid", "Select two different pins.")
                    return
                # Toggle both pins together
                curr_state = self.getswitch(dev1, pin1) and self.getswitch(dev2, pin2)
                new_state = 0 if curr_state else 1
                self.setswitch(dev1, pin1, new_state)
                self.setswitch(dev2, pin2, new_state)
                btn.setChecked(bool(new_state))
                self.set_style(btn, new_state)

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
