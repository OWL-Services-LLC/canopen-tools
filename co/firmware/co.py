import sys
import os
import canopen
import threading
import time
from datetime import datetime

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

MENU_TEXT = """
=== Main Menu ===
1) Add node
2) Send NMT command
3) Read SDO
4) Write SDO
5) Send PDO
6) Subscribe to TPDO
7) Subscribe to Heartbeat
8) Unsubscribe from TPDO
9) Unsubscribe from Heartbeat
10) List added nodes
11) Show node state
12) Show node OD info
13) Exit
Choose an option: 
"""

NMT_STATE_TEXT = {
    0: "Initializing",
    4: "Stopped",
    5: "Operational",
    127: "Pre-operational"
}

class EventMonitor:
    def __init__(self):
        self.subscribed_pdos = {}   # (node_id, pdo_num) -> (value, timestamp, eds_name)
        self.pdo_callbacks = {}     # (node_id, pdo_num) -> callback ref
        self.subscribed_hbs = {}    # node_id -> (state, timestamp, eds_name)
        self.hb_callbacks = {}      # node_id -> callback ref
        self.lock = threading.Lock()
        self.force_refresh = threading.Event()
        self.menu_renderer = None  # callback to print menu

    def subscribe_pdo(self, node, pdo_num, nodes_meta):
        key = (node.id, pdo_num)
        def pdo_callback(mapobject):
            with self.lock:
                self.subscribed_pdos[key] = (list(mapobject.values()), datetime.now(), nodes_meta[node.id])
            self.force_refresh.set()
        tpdo = node.tpdo[pdo_num]
        tpdo.add_callback(pdo_callback)
        self.pdo_callbacks[key] = pdo_callback

    def unsubscribe_pdo(self, node, pdo_num):
        key = (node.id, pdo_num)
        tpdo = node.tpdo[pdo_num]
        callback = self.pdo_callbacks.get(key)
        if callback:
            try:
                tpdo.remove_callback(callback)
            except Exception:
                pass
            with self.lock:
                self.subscribed_pdos.pop(key, None)
                self.pdo_callbacks.pop(key, None)
            self.force_refresh.set()

    def subscribe_heartbeat(self, node, nodes_meta):
        node_id = node.id
        def hb_callback(state):
            with self.lock:
                self.subscribed_hbs[node_id] = (state, datetime.now(), nodes_meta[node_id])
            self.force_refresh.set()
        # For older versions of python-canopen:
        try:
            node.nmt.add_heartbeat_callback(hb_callback)
        except AttributeError:
            node.nmt._callbacks.append(hb_callback)
        self.hb_callbacks[node_id] = hb_callback

    def unsubscribe_heartbeat(self, node):
        node_id = node.id
        callback = self.hb_callbacks.get(node_id)
        if callback:
            try:
                if hasattr(node.nmt, "remove_heartbeat_callback"):
                    node.nmt.remove_heartbeat_callback(callback)
                else:
                    node.nmt._callbacks.remove(callback)
            except Exception:
                pass
            with self.lock:
                self.subscribed_hbs.pop(node_id, None)
                self.hb_callbacks.pop(node_id, None)
            self.force_refresh.set()

    def render_monitor(self):
        with self.lock:
            print("="*50)
            print("=== Subscribed PDOs ===")
            if not self.subscribed_pdos:
                print("(no PDO subscriptions)")
            else:
                for (node_id, pdo_num), (value, ts, eds_name) in sorted(self.subscribed_pdos.items()):
                    print(f"Node {node_id} ({eds_name}) - PDO{pdo_num}: {value}, {ts.strftime('%H:%M:%S.%f')[:-3]}")
            print("=== Subscribed Heartbeats ===")
            if not self.subscribed_hbs:
                print("(no heartbeat subscriptions)")
            else:
                for node_id, (state, ts, eds_name) in sorted(self.subscribed_hbs.items()):
                    state_txt = NMT_STATE_TEXT.get(state, f"Unknown({state})")
                    print(f"Node {node_id} ({eds_name}): state={state_txt}, {ts.strftime('%H:%M:%S.%f')[:-3]}")
            print("="*50)

    def render_full(self):
        clear_screen()
        self.render_monitor()
        if self.menu_renderer:
            self.menu_renderer()

    def refresh_loop(self, get_in_main_menu):
        while True:
            self.force_refresh.wait()
            self.force_refresh.clear()
            if get_in_main_menu():
                self.render_full()

    def manual_refresh(self):
        self.render_full()

def load_eds_files(eds_paths):
    eds_files = []
    for path in eds_paths:
        if os.path.isfile(path):
            eds_files.append(path)
        else:
            print(f"Warning: EDS file not found: {path}")
    return eds_files

def choose_eds(eds_files):
    print("Available EDS files:")
    for idx, eds in enumerate(eds_files, start=1):
        print(f"{idx}) {os.path.basename(eds)}")
    while True:
        try:
            choice = int(input("Select EDS file by number: "))
            if 1 <= choice <= len(eds_files):
                return eds_files[choice - 1]
        except Exception:
            pass
        print("Invalid selection. Try again.")

def add_node(network, nodes, nodes_meta, eds_files):
    node_id = int(input("Enter node ID: "))
    eds = choose_eds(eds_files)
    node = canopen.RemoteNode(node_id, eds)
    network.add_node(node)
    nodes[node_id] = node
    nodes_meta[node_id] = os.path.basename(eds)
    print(f"Node {node_id} added with EDS '{os.path.basename(eds)}'.")

def list_od_entries(node):
    entries = []
    for idx, obj in node.object_dictionary.items():
        if hasattr(obj, "name") and obj.name != "":
            entries.append((idx, obj))
    entries.sort(key=lambda x: x[0])
    return entries

def choose_od_entry(node):
    entries = list_od_entries(node)
    print("Available SDO objects:")
    for idx, (index, obj) in enumerate(entries, start=1):
        print(f"{idx}) {hex(index)} - {obj.name}")
    while True:
        try:
            choice = int(input("Select SDO by number: "))
            if 1 <= choice <= len(entries):
                return entries[choice - 1]
        except Exception:
            pass
        print("Invalid selection. Try again.")

def is_array(obj):
    data_type = str(getattr(obj, 'data_type', '')).upper()
    return data_type == "ARRAY" or (hasattr(obj, 'subindices') and len(obj.subindices) > 1 and not is_record(obj))

def is_record(obj):
    data_type = str(getattr(obj, 'data_type', '')).upper()
    return data_type == "RECORD"

def is_octet_string(obj):
    data_type = str(getattr(obj, 'data_type', '')).upper()
    return "OCTET_STRING" in data_type or "STRING" in data_type

def write_sdo(node):
    (index, obj) = choose_od_entry(node)
    try:
        if is_array(obj):
            if is_octet_string(obj):
                val = input(f"Enter string or bytes for ARRAY '{obj.name}': ")
                bval = val.encode('utf-8')
                for i, byte in enumerate(bval, start=1):
                    try:
                        node.sdo[index][i].raw = byte
                    except Exception as e:
                        print(f"  Error writing byte at subindex {i}: {e}")
                print(f"Wrote {len(bval)} bytes to {obj.name}.")
            else:
                arr = input(f"Enter values for ARRAY '{obj.name}' (space or comma separated): ")
                if "," in arr:
                    values = [v.strip() for v in arr.split(",") if v.strip() != ""]
                else:
                    values = [v.strip() for v in arr.split() if v.strip() != ""]
                for i, val in enumerate(values, start=1):
                    try:
                        subobj = obj.subindices.get(i)
                        dtype = type(node.sdo[index][i].raw) if subobj else int
                        node.sdo[index][i].raw = dtype(val)
                    except Exception as e:
                        print(f"  Error writing subindex {i}: {e}")
                print(f"Wrote {len(values)} elements to {obj.name}.")
        elif is_record(obj):
            print(f"Writing RECORD '{obj.name}' field by field:")
            for sub, subobj in obj.subindices.items():
                if sub == 0 and len(obj.subindices) > 1:
                    continue
                current_val = None
                try:
                    current_val = node.sdo[index][sub].raw
                except Exception:
                    pass
                val = input(f"  [{hex(index)}:{hex(sub)}] {subobj.name} (current: {current_val}): ")
                try:
                    if val != "":
                        node.sdo[index][sub].raw = type(current_val)(val)
                except Exception as e:
                    print(f"    Error writing subindex {sub}: {e}")
            print("Write complete.")
        else:
            val = input(f"Enter value for VAR '{obj.name}': ")
            sdo_type = type(node.sdo[index].raw)
            try:
                if isinstance(node.sdo[index].raw, (bytes, bytearray)):
                    # Para OCTET_STRING/BYTE ARRAY
                    node.sdo[index].raw = val.encode("utf-8")
                else:
                    node.sdo[index].raw = sdo_type(val)
                print("Write complete.")
            except Exception as e:
                print(f"Error writing SDO: {e}")
    except Exception as e:
        print(f"Error writing SDO: {e}")
    print("\nPress Enter to go back to the main menu.")
    input()

def read_sdo(node):
    (index, obj) = choose_od_entry(node)
    try:
        if is_array(obj) or is_record(obj):
            print(f"Reading all subindices of {hex(index)} ({obj.name}):")
            for sub, subobj in obj.subindices.items():
                if sub == 0 and len(obj.subindices) > 1:
                    continue
                try:
                    val = node.sdo[index][sub].raw
                    print(f"  [{hex(index)}:{hex(sub)}] {subobj.name}: {val}")
                except Exception as e:
                    print(f"  [{hex(index)}:{hex(sub)}] {subobj.name}: Error ({e})")
        else:
            val = node.sdo[index].raw
            print(f"[{hex(index)}] {obj.name}: {val}")
    except Exception as e:
        print(f"Error reading SDO: {e}")
    print("\nPress Enter to go back to the main menu.")
    input()

def choose_node(nodes, nodes_meta):
    if not nodes:
        print("No nodes found. Please add a node first.")
        return None
    node_ids = list(nodes.keys())
    print("Available nodes:")
    for idx, node_id in enumerate(node_ids, start=1):
        print(f"{idx}) Node ID {node_id} - {nodes_meta[node_id]}")
    while True:
        try:
            choice = int(input("Select node by number: "))
            if 1 <= choice <= len(node_ids):
                return nodes[node_ids[choice - 1]]
        except Exception:
            pass
        print("Invalid selection. Try again.")

def send_nmt(network, nodes, nodes_meta):
    node = choose_node(nodes, nodes_meta)
    if node is None:
        return
    node_id = node.id
    nmt_cmds = [
        ("start", 0x01),
        ("stop", 0x02),
        ("pre-op", 0x80),
        ("reset node", 0x81),
        ("reset comm", 0x82)
    ]
    print("NMT Commands:")
    for idx, (name, _) in enumerate(nmt_cmds, start=1):
        print(f"{idx}) {name}")
    while True:
        try:
            choice = int(input("Choose command by number: "))
            if 1 <= choice <= len(nmt_cmds):
                cmd_name, cmd_code = nmt_cmds[choice - 1]
                break
        except Exception:
            pass
        print("Invalid selection. Try again.")
    try:
        node.nmt.send_command(cmd_code)
        print(f"NMT '{cmd_name}' sent to node {node_id}")
    except Exception as e:
        print(f"Error sending NMT command: {e}")

def send_pdo(nodes, nodes_meta):
    node = choose_node(nodes, nodes_meta)
    if node is None:
        return
    try:
        rpdo_count = len(node.rpdo)
        if rpdo_count == 0:
            print("No RPDOs found in EDS for this node.")
            return
        print(f"Node has {rpdo_count} RPDO(s):")
        for i in range(1, rpdo_count + 1):
            print(f"{i}) RPDO {i}")
        while True:
            try:
                pdo_num = int(input(f"Select RPDO by number (1..{rpdo_count}): "))
                if 1 <= pdo_num <= rpdo_count:
                    break
            except Exception:
                pass
            print("Invalid selection. Try again.")
        rpdo = node.rpdo[pdo_num]
        values = []
        print("Enter values (space or comma separated):")
        var_count = len(rpdo.maps)
        if var_count == 0:
            print("No variables mapped to this RPDO.")
            return
        for idx, var in enumerate(rpdo.maps, start=1):
            print(f"  {idx}) {var.name}")
        vals_input = input("Values: ")
        if "," in vals_input:
            val_list = [v.strip() for v in vals_input.split(",") if v.strip() != ""]
        else:
            val_list = [v.strip() for v in vals_input.split() if v.strip() != ""]
        if len(val_list) != var_count:
            print(f"Expected {var_count} values, got {len(val_list)}.")
            return
        for v, var in zip(val_list, rpdo.maps):
            dtype = var.data_type.pytype if hasattr(var.data_type, 'pytype') else int
            values.append(dtype(v))
        rpdo.data = values
        rpdo.transmit()
        print("RPDO transmitted.")
    except Exception as e:
        print(f"Error sending PDO: {e}")

def subscribe_tpdo(nodes, nodes_meta, monitor):
    node = choose_node(nodes, nodes_meta)
    if node is None:
        return
    try:
        tpdo_count = len(node.tpdo)
        if tpdo_count == 0:
            print("No TPDOs found in EDS for this node.")
            print("\nPress Enter to go back to the main menu."); input()
            return
        print(f"Node has {tpdo_count} TPDO(s):")
        for i in range(1, tpdo_count + 1):
            print(f"{i}) TPDO {i}")
        while True:
            try:
                pdo_num = int(input(f"Select TPDO by number (1..{tpdo_count}): "))
                if 1 <= pdo_num <= tpdo_count:
                    break
            except Exception:
                pass
            print("Invalid selection. Try again.")
        monitor.subscribe_pdo(node, pdo_num, nodes_meta)
        print(f"Subscribed to Node {node.id} TPDO {pdo_num}. You will now see PDO events in the main menu.")
        print("\nPress Enter to go back to the main menu."); input()
    except Exception as e:
        print(f"Error subscribing to TPDO: {e}")
        print("\nPress Enter to go back to the main menu."); input()

def subscribe_heartbeat(nodes, nodes_meta, monitor):
    node = choose_node(nodes, nodes_meta)
    if node is None:
        return
    try:
        monitor.subscribe_heartbeat(node, nodes_meta)
        print(f"Subscribed to heartbeat of Node {node.id}. You will now see heartbeat events in the main menu.")
    except Exception as e:
        print(f"Error subscribing to heartbeat: {e}")

def unsubscribe_tpdo(nodes, nodes_meta, monitor):
    with monitor.lock:
        current = list(monitor.subscribed_pdos.keys())
    if not current:
        print("No active TPDO subscriptions.")
        return
    print("Active TPDO subscriptions:")
    for idx, (node_id, pdo_num) in enumerate(current, start=1):
        eds_name = nodes_meta.get(node_id, "?")
        print(f"{idx}) Node {node_id} ({eds_name}) - PDO{pdo_num}")
    while True:
        try:
            choice = int(input("Select TPDO to unsubscribe by number: "))
            if 1 <= choice <= len(current):
                break
        except Exception:
            pass
        print("Invalid selection. Try again.")
    node_id, pdo_num = current[choice - 1]
    node = nodes.get(node_id)
    if node:
        monitor.unsubscribe_pdo(node, pdo_num)
        print(f"Unsubscribed from Node {node_id} TPDO {pdo_num}.")
    else:
        print("Node not found.")

def unsubscribe_heartbeat(nodes, nodes_meta, monitor):
    with monitor.lock:
        current = list(monitor.subscribed_hbs.keys())
    if not current:
        print("No active heartbeat subscriptions.")
        return
    print("Active heartbeat subscriptions:")
    for idx, node_id in enumerate(current, start=1):
        eds_name = nodes_meta.get(node_id, "?")
        print(f"{idx}) Node {node_id} ({eds_name})")
    while True:
        try:
            choice = int(input("Select heartbeat to unsubscribe by number: "))
            if 1 <= choice <= len(current):
                break
        except Exception:
            pass
        print("Invalid selection. Try again.")
    node_id = current[choice - 1]
    node = nodes.get(node_id)
    if node:
        monitor.unsubscribe_heartbeat(node)
        print(f"Unsubscribed from Node {node_id} heartbeat.")
    else:
        print("Node not found.")

def list_nodes(nodes, nodes_meta):
    clear_screen()
    if not nodes:
        print("No nodes have been added yet.")
    else:
        print("=== Added Nodes ===")
        for node_id, node in nodes.items():
            eds_name = nodes_meta.get(node_id, "?")
            print(f"Node ID {node_id} - {eds_name}")
        print("="*24)
    print("\nPress Enter to go back to the main menu.")
    input()

def show_node_state(nodes, nodes_meta):
    node = choose_node(nodes, nodes_meta)
    if node is None:
        return
    try:
        # Read actual NMT state from heartbeat or ask node
        state = node.nmt.state
        state_txt = NMT_STATE_TEXT.get(state, f"Unknown({state})")
        print(f"\nNode {node.id} ({nodes_meta[node.id]}) NMT State: {state_txt} ({state})")
    except Exception as e:
        print(f"Could not retrieve node state: {e}")
    print("\nPress Enter to go back to the main menu.")
    input()

def show_node_od_info(nodes, nodes_meta):
    node = choose_node(nodes, nodes_meta)
    if node is None:
        return
    print(f"\n=== Object Dictionary for Node {node.id} ({nodes_meta[node.id]}) ===")
    print(f"{'Index':>8}  {'Name':<32} {'Type':<12} {'Access':<10} {'Description'}")
    print('-'*80)
    for idx, obj in list_od_entries(node):
        dtype = str(getattr(obj, 'data_type', '')) if hasattr(obj, 'data_type') else ''
        access = getattr(obj, 'access_type', '') if hasattr(obj, 'access_type') else ''
        desc = getattr(obj, 'description', '') if hasattr(obj, 'description') else ''
        print(f"{hex(idx):>8}  {obj.name:<32} {dtype:<12} {access:<10} {desc}")
    print("-"*80)
    print("\nPress Enter to go back to the main menu.")
    input()

def render_menu():
    print(MENU_TEXT, end="")

def main():
    if len(sys.argv) < 2:
        print("Usage: python co.py <eds1.eds,eds2.eds,...>")
        sys.exit(1)
    eds_files = load_eds_files(sys.argv[1].split(','))

    interface = input("Enter CAN interface (default 'vcan0'): ").strip()
    if interface == "":
        interface = "vcan0"
    baud_str = input("Enter baudrate (default 125000): ").strip()
    baudrate = int(baud_str) if baud_str != "" else 125000
    network = canopen.Network()
    network.connect(bustype='socketcan', channel=interface, bitrate=baudrate)
    print("Connection established.")

    nodes = {}       # node_id -> canopen.RemoteNode
    nodes_meta = {}  # node_id -> EDS base name

    in_main_menu = [True]
    monitor = EventMonitor()
    monitor.menu_renderer = render_menu
    monitor_thread = threading.Thread(target=monitor.refresh_loop, args=(lambda: in_main_menu[0],), daemon=True)
    monitor_thread.start()

    try:
        while True:
            in_main_menu[0] = True
            monitor.manual_refresh()
            op = input("").strip()
            in_main_menu[0] = False
            if op == "1":
                add_node(network, nodes, nodes_meta, eds_files)
            elif op == "2":
                send_nmt(network, nodes, nodes_meta)
            elif op == "3":
                node = choose_node(nodes, nodes_meta)
                if node:
                    read_sdo(node)
            elif op == "4":
                node = choose_node(nodes, nodes_meta)
                if node:
                    write_sdo(node)
            elif op == "5":
                send_pdo(nodes, nodes_meta)
            elif op == "6":
                subscribe_tpdo(nodes, nodes_meta, monitor)
            elif op == "7":
                subscribe_heartbeat(nodes, nodes_meta, monitor)
            elif op == "8":
                unsubscribe_tpdo(nodes, nodes_meta, monitor)
            elif op == "9":
                unsubscribe_heartbeat(nodes, nodes_meta, monitor)
            elif op == "10":
                list_nodes(nodes, nodes_meta)
            elif op == "11":
                show_node_state(nodes, nodes_meta)
            elif op == "12":
                show_node_od_info(nodes, nodes_meta)
            elif op == "13":
                network.disconnect()
                break
            else:
                print("Invalid option.")
    except KeyboardInterrupt:
        network.disconnect()

if __name__ == "__main__":
    main()
