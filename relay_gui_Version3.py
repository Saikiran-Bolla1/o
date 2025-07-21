import sys
import csv
import json
import traceback
import time
import serial
import win32com.client
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QTextEdit, QMessageBox, QScrollArea, QMainWindow, QDockWidget, QAction
)
from PyQt5.QtCore import Qt, QTimer

# ---- NUMATO RELAY HARDWARE MODULE BEGIN ----
class NumatoRelay:
    def __init__(self):
        self.InitDone = 0
        self.baudrate = 19200
        self.NumatoPorts = []
        self.Device_obj = []
        self.NumHandlDic = {}

    def init(self, console_callback=None):
        try:
            self.NumatoPorts = []
            self.Device_obj = []
            self.NumHandlDic = {}
            wmi = win32com.client.GetObject("winmgmts:")
            for eachPort in wmi.InstancesOf("Win32_SerialPort"):
                SerportName = eachPort.Name
                if str(SerportName).find("USB Serial Device") != -1:
                    self.NumatoPorts.append(str(SerportName.split("(")[1][:-1]))
            self.Device_obj = [p for p in self.NumatoPorts]
            for each_port in self.Device_obj:
                devType = "USB Serial Device"
                DeviceNumber = serial.Serial(each_port, self.baudrate, timeout=1)
                DeviceNumber.write(str.encode('id get\r'))
                time.sleep(0.1)
                response = DeviceNumber.read(100).decode(errors='ignore')
                try:
                    DeviceID = response.split('\r')[1].split('\n')[0]
                except Exception:
                    DeviceID = ""
                if DeviceID != "":
                    self.NumHandlDic[DeviceID] = {'DeviceNumber': each_port, 'DeviceType': devType}
                DeviceNumber.write(str.encode('relay writeall 000000\r'))
                DeviceNumber.close()
            self.InitDone = 1
            msg = "NumatoRelay: Connected (init successful)"
            if console_callback:
                console_callback(msg)
        except Exception as e:
            msg = f"NumatoRelay: Init failed: {e}\n{traceback.format_exc()}"
            if console_callback:
                console_callback(msg)
            self.InitDone = 0

    def deinit(self, console_callback=None):
        try:
            if self.InitDone == 1:
                for each_port in self.Device_obj:
                    try:
                        DeviceNumber = serial.Serial(each_port, self.baudrate, timeout=1)
                        DeviceNumber.close()
                    except Exception:
                        pass
                self.NumHandlDic = {}
                self.InitDone = 0
                msg = "NumatoRelay: Disconnected (deinit successful)"
                if console_callback:
                    console_callback(msg)
        except Exception as e:
            msg = f"NumatoRelay: Deinit failed: {e}\n{traceback.format_exc()}"
            if console_callback:
                console_callback(msg)

    def setswitch(self, device_id, pin_no, value, console_callback=None):
        try:
            max_retries = 3
            attempts = 0
            while attempts < max_retries:
                try:
                    device_info = self.NumHandlDic[device_id]
                    port = device_info['DeviceNumber']
                    serPort = serial.Serial(port, self.baudrate, timeout=1)
                    serPort.write(str.encode('id get\r'))
                    time.sleep(0.1)
                    response = serPort.read_all().decode(errors='ignore')
                    lines = response.splitlines()
                    DeviceID_resp = ""
                    for line in lines:
                        line = line.strip()
                        if line and line.isalnum():
                            DeviceID_resp = line
                            break
                    if DeviceID_resp == device_id:
                        relayIndex = str(pin_no) if int(pin_no) < 10 else chr(55 + int(pin_no))
                        relayCmd = 'on' if int(value) == 1 else 'off'
                        serPort.write(str.encode(f'relay {relayCmd} {relayIndex}\r\n'))
                        msg = f"NumatoRelay: setswitch sent {relayCmd} to device {device_id} on switch {pin_no}"
                        if console_callback:
                            console_callback(msg)
                        serPort.close()
                        return
                    else:
                        msg = f"NumatoRelay: DeviceID mismatch. Expected {device_id}, got {DeviceID_resp}"
                        if console_callback:
                            console_callback(msg)
                        serPort.close()
                        return
                except KeyError:
                    msg = f"NumatoRelay: Invalid device ID: {device_id}"
                    if console_callback:
                        console_callback(msg)
                    break
                except serial.SerialException as se:
                    attempts += 1
                    msg = f"NumatoRelay: Serial error on attempt {attempts}: {se}"
                    if console_callback:
                        console_callback(msg)
                except Exception as e:
                    attempts += 1
                    msg = f"NumatoRelay: Unexpected error on attempt {attempts}: {e}"
                    if console_callback:
                        console_callback(msg)
                finally:
                    try:
                        if 'serPort' in locals() and serPort.is_open:
                            serPort.close()
                    except Exception:
                        pass
            final_msg = f"NumatoRelay: Failed to set switch after {max_retries} attempts for device {device_id}"
            if console_callback:
                console_callback(final_msg)
        except Exception as e:
            msg = f"NumatoRelay: setswitch failed: {e}\n{traceback.format_exc()}"
            if console_callback:
                console_callback(msg)

    def getswitch(self, device_id, pin_no, console_callback=None):
        try:
            device_info = self.NumHandlDic[device_id]
            port = device_info['DeviceNumber']
            serPort = serial.Serial(port, self.baudrate, timeout=1)
            serPort.write(str.encode('id get\r'))
            time.sleep(0.1)
            response = serPort.read_all().decode(errors='ignore')
            lines = response.splitlines()
            DeviceID_resp = ""
            for line in lines:
                line = line.strip()
                if line and line.isalnum():
                    DeviceID_resp = line
                    break
            if DeviceID_resp == device_id:
                relayIndex = str(pin_no) if int(pin_no) < 10 else chr(55 + int(pin_no))
                serPort.write(str.encode(f'relay read {relayIndex}\r\n'))
                time.sleep(0.1)
                try:
                    iValue = (serPort.read(100)).decode().split('\r')[1].split('\n')[0]
                except Exception:
                    iValue = "0"
                msg = f"NumatoRelay: getswitch(DeviceID={device_id}, pin={pin_no}) = {iValue}"
                if console_callback:
                    console_callback(msg)
                serPort.close()
                return int(iValue)
            else:
                msg = f"NumatoRelay: DeviceID mismatch. Expected {device_id}, got {DeviceID_resp}"
                if console_callback:
                    console_callback(msg)
                serPort.close()
                return 0
        except Exception as e:
            msg = f"NumatoRelay: getswitch failed: {e}\n{traceback.format_exc()}"
            if console_callback:
                console_callback(msg)
            return 0

    def clearrelays(self, console_callback=None):
        try:
            for device_id, device_info in self.NumHandlDic.items():
                port = device_info['DeviceNumber']
                serPort = serial.Serial(port, self.baudrate, timeout=1)
                serPort.write(str.encode('relay writeall 000000\r'))
                serPort.close()
            msg = "NumatoRelay: All relays cleared (clearrelays successful)"
            if console_callback:
                console_callback(msg)
        except Exception as e:
            msg = f"NumatoRelay: clearrelays failed: {e}\n{traceback.format_exc()}"
            if console_callback:
                console_callback(msg)
# ---- NUMATO RELAY HARDWARE MODULE END ----

GROUPS_PER_PAGE = 12
ACTION_TYPES = ["OpenLoad", "ShortToUBat", "ShortToGND", "ShortToPin"]

# Instantiate the relay hardware globally
relay_hw = NumatoRelay()

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

        # Serial Port Indicator, Connect/Disconnect Buttons
        self.serial_indicator = QLabel("Serial: Disconnected")
        self.serial_indicator.setStyleSheet("color: red; font-weight: bold;")
        nav_layout.addWidget(self.serial_indicator)
        self.serial_connect_btn = QPushButton("Connect All")
        self.serial_connect_btn.clicked.connect(self.connect_all_serial_ports)
        nav_layout.addWidget(self.serial_connect_btn)
        self.serial_disconnect_btn = QPushButton("Disconnect All")
        self.serial_disconnect_btn.clicked.connect(self.disconnect_all_serial_ports)
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
        self.console.setContextMenuPolicy(Qt.CustomContextMenu)
        self.console.customContextMenuRequested.connect(self.show_console_context_menu)
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
        clear_console_action = QAction("Clear Console", self)  # <---- Added
        clear_console_action.triggered.connect(self.clear_console)  # <---- Added
        file_menu.addAction(clear_console_action)  # <---- Added

        view_menu = menubar.addMenu("View")
        reset_action = QAction("Reset", self)
        reset_action.triggered.connect(self.reset_view)
        view_menu.addAction(reset_action)
        view_menu.addAction(self.pin_action)

        try:
            relay_hw.init(self.console.append)
            self.console.append("Relay hardware initialized.")
        except Exception as e:
            self.console.append(f"Relay hardware init failed: {e}")
        self.update_serial_indicator()

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
    # --- Force widget/layout update here ---
    self.groups_widget.adjustSize()
    self.groups_widget.update()
    self.scroll_area.update()

    def make_toggle_callback(self, group_idx, action, btn):
        def callback(checked):
            self.toggle_switch(group_idx, action, btn)
            # Immediate color feedback for UI
            self.set_style(btn, btn.isChecked())
        return callback

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

        # Wait a short time for hardware state to settle, then update the UI
        QTimer.singleShot(200, self.update_page)

    def setswitch(self, device_id, pin_no, value):
        try:
            relay_hw.setswitch(device_id, pin_no, value, self.console.append)
            self.console.append(f"setswitch(DeviceID={device_id}, PinNo={pin_no}, value={value})")
        except Exception as e:
            self.console.append(f"Error setting relay: {device_id},{pin_no} to {value}: {e}")

    def getswitch(self, device_id, pin_no):
        try:
            return relay_hw.getswitch(device_id, pin_no, self.console.append)
        except Exception as e:
            self.console.append(f"Error reading relay: {device_id},{pin_no}: {e}")
            return 0

    def clear_relays(self):
        try:
            relay_hw.clearrelays(self.console.append)
            self.console.append("All relays have been cleared (set to OFF).")
            self.active_faults = {}
            self.shorttopin_selected = set()
            self.update_page()
        except Exception as e:
            self.console.append(f"Failed to clear relays: {e}")

    def closeEvent(self, event):
        try:
            relay_hw.deinit(self.console.append)
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

    def connect_all_serial_ports(self):
        try:
            relay_hw.init(self.console.append)
            self.console.append("All serial ports connected.")
            self.update_serial_indicator()
        except Exception as e:
            self.console.append(f"Failed to connect all serial ports: {e}")
            self.update_serial_indicator()

    def disconnect_all_serial_ports(self):
        try:
            relay_hw.deinit(self.console.append)
            self.console.append("All serial ports disconnected.")
            self.update_serial_indicator()
        except Exception as e:
            self.console.append(f"Failed to disconnect all serial ports: {e}")
            self.update_serial_indicator()

    def update_serial_indicator(self):
        if relay_hw.InitDone:
            self.serial_indicator.setText("Serial: Connected (All)")
            self.serial_indicator.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.serial_indicator.setText("Serial: Disconnected")
            self.serial_indicator.setStyleSheet("color: red; font-weight: bold;")

    def show_console_context_menu(self, pos):
        menu = self.console.createStandardContextMenu()
        menu.addSeparator()
        clear_action = QAction("Clear Console", self.console)
        clear_action.triggered.connect(self.clear_console)
        menu.addAction(clear_action)
        menu.exec_(self.console.mapToGlobal(pos))
        
    def clear_console(self):
        self.console.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RelayControl()
    window.show()
    sys.exit(app.exec_())
