import sys
import csv
import json
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QTextEdit, QMessageBox, QScrollArea, QMainWindow, QDockWidget, QAction, QComboBox
)
from PyQt5.QtCore import Qt

# ---- RELAY HARDWARE MODULE BEGIN ----
# This section simulates relay_hw.py functionality.
# Replace these stubs with your actual relay board code.

class RelayHW:
    def __init__(self):
        self.relays = {}  # (device_id, pin_no): value

    def init(self):
        # Initialize hardware/serial
        print("RelayHW: Initialized")

    def deinit(self):
        # Deinitialize hardware/serial
        print("RelayHW: Deinitialized")

    def setswitch(self, device_id, pin_no, value):
        # Set relay to value (0/1)
        self.relays[(device_id, pin_no)] = value

    def getswitch(self, device_id, pin_no):
        # Return relay state (0/1)
        return self.relays.get((device_id, pin_no), 0)

    def reset_all_relays(self):
        # Set all relays to 0
        keys = list(self.relays.keys())
        for k in keys:
            self.relays[k] = 0
        print("RelayHW: All relays reset.")

relay_hw = RelayHW()
# ---- RELAY HARDWARE MODULE END ----

GROUPS_PER_PAGE = 12
ACTION_TYPES = ["OpenLoad", "ShortToUBat", "ShortToGND", "ShortToPin"]

class RelayControl(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Numato Relay Controller - Paginated Groups")
        self.resize(1200, 800)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.groups = []
        self.group_line_keys = []
        self.current_page = 0
        self.fault_map = {}
        self.active_faults = {}
        self.shorttopin_selected = set()

        # Main layout
        main_layout = QVBoxLayout(central_widget)
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("Previous")
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn = QPushButton("Next")
        self.next_btn.clicked.connect(self.next_page)
        self.page_label = QLabel("Page 1")
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addStretch()

        # Serial Port Indicator, Controls (simulated)
        self.serial_indicator = QLabel("Serial: Disconnected")
        self.serial_indicator.setStyleSheet("color: red; font-weight: bold;")
        nav_layout.addWidget(self.serial_indicator)

        self.serial_port_selector = QComboBox()
        self.serial_port_selector.addItem("COM1")
        self.serial_port_selector.addItem("COM2")
        self.serial_port_selector.addItem("COM3")
        self.serial_port_selector.addItem("COM4")
        self.serial_port_selector.addItem("COM5")
        self.serial_port_selector.addItem("COM6")
        self.serial_port_selector.addItem("COM7")
        self.serial_port_selector.addItem("COM8")
        self.serial_port_selector.addItem("COM9")
        self.serial_port_selector.addItem("COM10")
        self.serial_port_selector.addItem("COM11")
        self.serial_port_selector.addItem("COM12")
        self.serial_port_selector.addItem("COM13")
        self.serial_port_selector.addItem("COM14")
        self.serial_port_selector.setMinimumWidth(100)
        nav_layout.addWidget(self.serial_port_selector)
        self.serial_connect_btn = QPushButton("Connect")
        self.serial_connect_btn.clicked.connect(self.connect_serial_port)
        nav_layout.addWidget(self.serial_connect_btn)
        self.serial_disconnect_btn = QPushButton("Disconnect")
        self.serial_disconnect_btn.clicked.connect(self.disconnect_serial_port)
        nav_layout.addWidget(self.serial_disconnect_btn)

        main_layout.addLayout(nav_layout)

        self.scroll_area = QScrollArea()
        self.groups_widget = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_widget)
        self.groups_widget.setLayout(self.groups_layout)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.groups_widget)
        main_layout.addWidget(self.scroll_area, stretch=1)

        # Console as dockable widget
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console_dock = QDockWidget("Console Output", self)
        self.console_dock.setWidget(self.console)
        self.console_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)

        self.pin_action = QAction("Pin Console", self)
        self.pin_action.setCheckable(True)
        self.pin_action.setChecked(True)
        self.pin_action.triggered.connect(self.toggle_pin_console)
        self.console_dock.visibilityChanged.connect(self.on_console_visibility_changed)

        # Menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        clear_relays_action = QAction("Clear Relays", self)
        clear_relays_action.triggered.connect(self.clear_relays)
        file_menu.addAction(clear_relays_action)
        load_json_action = QAction("Load JSON", self)
        load_json_action.triggered.connect(self.load_fault_json)
        file_menu.addAction(load_json_action)
        load_csv_action = QAction("Load GroupNames CSV", self)
        load_csv_action.triggered.connect(self.load_groups)
        file_menu.addAction(load_csv_action)

        view_menu = menubar.addMenu("View")
        reset_action = QAction("Reset", self)
        reset_action.triggered.connect(self.reset_view)
        view_menu.addAction(reset_action)
        view_menu.addAction(self.pin_action)

        # Simulate relay hardware init and serial disconnected
        try:
            relay_hw.init()
            self.console.append("Relay hardware initialized.")
        except Exception as e:
            self.console.append(f"Relay hardware init failed: {e}")
        self.serial_port_connected = False

        self.set_default_groups()
        self.update_page()

    def set_default_groups(self):
        self.groups = [f"Group {i+1}" for i in range(108)]
        self.group_line_keys = [f"Line_{i+1:02d}" for i in range(108)]

    def reset_view(self):
        self.current_page = 0
        self.set_default_groups()
        self.fault_map = {}
        self.active_faults = {}
        self.shorttopin_selected = set()
        self.console.clear()
        self.update_page()

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

    def deactivate_fault(self, group_idx, action):
        line_key = self.group_line_keys[group_idx]
        fault_entry = self.fault_map.get(line_key, {})
        if action == "OpenLoad":
            entry = fault_entry.get("OpenLoad")
            if entry:
                self.setswitch(entry.get('DeviceID'), entry.get('PinNo'), 0)
        elif action == "ShortToUBat":
            entry1 = fault_entry.get("Common")
            entry2 = fault_entry.get("UBat")
            if entry1 and entry2:
                self.setswitch(entry1.get('DeviceID'), entry1.get('PinNo'), 0)
                self.setswitch(entry2.get('DeviceID'), entry2.get('PinNo'), 0)
        elif action == "ShortToGND":
            entry1 = fault_entry.get("Common")
            entry2 = fault_entry.get("GND")
            if entry1 and entry2:
                self.setswitch(entry1.get('DeviceID'), entry1.get('PinNo'), 0)
                self.setswitch(entry2.get('DeviceID'), entry2.get('PinNo'), 0)
        elif action == "ShortToPin":
            entry = fault_entry.get("Common")
            if entry:
                self.setswitch(entry.get('DeviceID'), entry.get('PinNo'), 0)
            self.shorttopin_selected.discard(group_idx)

    def deactivate_all_faults_in_group(self, group_idx):
        for action in ACTION_TYPES:
            self.deactivate_fault(group_idx, action)

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
            entry = fault_entry.get("Common")
            return group_idx in self.shorttopin_selected and entry and self.getswitch(entry.get('DeviceID'), entry.get('PinNo')) == 1
        return False

    def toggle_switch(self, group_idx, action, btn):
        if self.is_fault_active(group_idx, action):
            self.deactivate_fault(group_idx, action)
            self.active_faults.pop(group_idx, None)
        else:
            self.deactivate_all_faults_in_group(group_idx)
            line_key = self.group_line_keys[group_idx]
            fault_entry = self.fault_map.get(line_key, {})
            if action == "OpenLoad":
                entry = fault_entry.get("OpenLoad")
                if entry:
                    self.setswitch(entry.get('DeviceID'), entry.get('PinNo'), 1)
            elif action == "ShortToUBat":
                entry1 = fault_entry.get("Common")
                entry2 = fault_entry.get("UBat")
                if entry1 and entry2:
                    self.setswitch(entry1.get('DeviceID'), entry1.get('PinNo'), 1)
                    self.setswitch(entry2.get('DeviceID'), entry2.get('PinNo'), 1)
            elif action == "ShortToGND":
                entry1 = fault_entry.get("Common")
                entry2 = fault_entry.get("GND")
                if entry1 and entry2:
                    self.setswitch(entry1.get('DeviceID'), entry1.get('PinNo'), 1)
                    self.setswitch(entry2.get('DeviceID'), entry2.get('PinNo'), 1)
            elif action == "ShortToPin":
                entry = fault_entry.get("Common")
                if entry:
                    self.setswitch(entry.get('DeviceID'), entry.get('PinNo'), 1)
                self.shorttopin_selected.add(group_idx)
            self.active_faults[group_idx] = action
        self.update_page()

    def setswitch(self, device_id, pin_no, value):
        try:
            relay_hw.setswitch(device_id, pin_no, value)
            self.console.append(f"setswitch(DeviceID={device_id}, PinNo={pin_no}, value={value})")
        except Exception as e:
            self.console.append(f"Error setting relay: {device_id},{pin_no} to {value}: {e}")

    def getswitch(self, device_id, pin_no):
        try:
            return relay_hw.getswitch(device_id, pin_no)
        except Exception as e:
            self.console.append(f"Error reading relay: {device_id},{pin_no}: {e}")
            return 0

    def clear_relays(self):
        try:
            relay_hw.reset_all_relays()
            self.console.append("All relays have been cleared (set to OFF).")
            self.active_faults = {}
            self.shorttopin_selected = set()
            self.update_page()
        except Exception as e:
            self.console.append(f"Failed to clear relays: {e}")

    def closeEvent(self, event):
        try:
            relay_hw.deinit()
            self.console.append("Relay hardware deinitialized.")
        except Exception as e:
            self.console.append(f"Relay hardware deinit failed: {e}")
        event.accept()

    def toggle_pin_console(self):
        if self.pin_action.isChecked():
            self.addDockWidget(Qt.BottomDockWidgetArea, self.console_dock)
            self.console_dock.setFloating(False)
            self.console_dock.setVisible(True)
            self.pin_action.setText("Pin Console")
        else:
            self.console_dock.setFloating(True)
            self.console_dock.setVisible(True)
            self.pin_action.setText("Unpin Console")

    def on_console_visibility_changed(self, visible):
        if not visible:
            self.pin_action.setChecked(False)

    # Serial connection simulation (for real use, replace with pyserial)
    def connect_serial_port(self):
        port = self.serial_port_selector.currentText()
        if self.serial_port_connected:
            self.console.append(f"Already connected to serial port: {port}")
            self.serial_indicator.setText(f"Serial: Connected ({port})")
            self.serial_indicator.setStyleSheet("color: green; font-weight: bold;")
            return
        try:
            # Simulate connection success
            self.serial_port_connected = True
            self.serial_indicator.setText(f"Serial: Connected ({port})")
            self.serial_indicator.setStyleSheet("color: green; font-weight: bold;")
            self.console.append(f"Connected to serial port: {port}")
        except Exception as e:
            self.console.append(f"Failed to connect to serial port {port}: {e}")
            self.serial_indicator.setText("Serial: Disconnected")
            self.serial_indicator.setStyleSheet("color: red; font-weight: bold;")
            self.serial_port_connected = False

    def disconnect_serial_port(self):
        if self.serial_port_connected:
            port = self.serial_port_selector.currentText()
            self.serial_port_connected = False
            self.serial_indicator.setText("Serial: Disconnected")
            self.serial_indicator.setStyleSheet("color: red; font-weight: bold;")
            self.console.append(f"Disconnected from serial port: {port}")
        else:
            self.console.append("No serial port connected.")
            self.serial_indicator.setText("Serial: Disconnected")
            self.serial_indicator.setStyleSheet("color: red; font-weight: bold;")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RelayControl()
    window.show()
    sys.exit(app.exec_())
