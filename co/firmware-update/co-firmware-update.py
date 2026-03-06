# Standalone CLI script for CANopen firmware update.
#
# Usage:
#   python co-firmware-update.py --node-id 1 --bin /path/to/zephyr.signed.bin
#   python co-firmware-update.py --node-id 1 --bin /path/to/zephyr.signed.bin --interface can0 --baudrate 500000

import argparse
import os
import sys
import time

try:
    import canopen
except ImportError:
    print("Error: python-canopen is not installed. Run: pip install canopen")
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None

# Default config file
DEFAULT_CONFIG = "co-firmware-update.yaml"

# Timeouts
DEFAULT_TIMEOUT     = 60.0  # seconds
DEFAULT_SDO_TIMEOUT = 10.0  # seconds
DEFAULT_SDO_RETRIES = 1
DEFAULT_BUFFER_SIZE = 1024

# Object dictionary indexes
H1F50_PROGRAM_DATA = 0x1F50
H1F51_PROGRAM_CTRL = 0x1F51
H1F56_PROGRAM_SWID = 0x1F56
H1F57_FLASH_STATUS = 0x1F57
PROGRAM_NUMBER     = 1

# Program control commands
PROGRAM_CTRL_STOP    = 0x00
PROGRAM_CTRL_START   = 0x01
PROGRAM_CTRL_CLEAR   = 0x03
PROGRAM_CTRL_CONFIRM = 0x80


def load_config(config_path=DEFAULT_CONFIG):
    config = {}
    if yaml is None:
        print(f"Warning: PyYAML not installed, ignoring config file {config_path}")
        return config
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: could not read config file {config_path}: {e}")
    return config


def create_flash_object_dictionary():
    objdict = canopen.objectdictionary.ObjectDictionary()

    array = canopen.objectdictionary.Array('Program data', H1F50_PROGRAM_DATA)
    member = canopen.objectdictionary.Variable('', H1F50_PROGRAM_DATA, subindex=1)
    member.data_type = canopen.objectdictionary.DOMAIN
    array.add_member(member)
    objdict.add_object(array)

    array = canopen.objectdictionary.Array('Program control', H1F51_PROGRAM_CTRL)
    member = canopen.objectdictionary.Variable('', H1F51_PROGRAM_CTRL, subindex=1)
    member.data_type = canopen.objectdictionary.UNSIGNED8
    array.add_member(member)
    objdict.add_object(array)

    array = canopen.objectdictionary.Array('Program software ID', H1F56_PROGRAM_SWID)
    member = canopen.objectdictionary.Variable('', H1F56_PROGRAM_SWID, subindex=1)
    member.data_type = canopen.objectdictionary.UNSIGNED32
    array.add_member(member)
    objdict.add_object(array)

    array = canopen.objectdictionary.Array('Flash error ID', H1F57_FLASH_STATUS)
    member = canopen.objectdictionary.Variable('', H1F57_FLASH_STATUS, subindex=1)
    member.data_type = canopen.objectdictionary.UNSIGNED32
    array.add_member(member)
    objdict.add_object(array)

    return objdict


def wait_for_flash_status_ok(flash_node, timeout=DEFAULT_TIMEOUT):
    end_time = time.time() + timeout
    status = 0xFFFFFFFF
    while True:
        try:
            status = flash_node.sdo[H1F57_FLASH_STATUS][PROGRAM_NUMBER].raw
            if status == 0:
                return status
        except Exception:
            pass
        if time.time() > end_time:
            return status
        time.sleep(0.5)


def flash_firmware(node_id, bin_path, interface, baudrate):
    network = canopen.Network()
    flash_node = network.add_node(node_id, create_flash_object_dictionary())
    flash_node.sdo.RESPONSE_TIMEOUT = DEFAULT_SDO_TIMEOUT
    flash_node.sdo.MAX_RETRIES = DEFAULT_SDO_RETRIES

    print(f"Connecting to {interface} at {baudrate} baud...")
    network.connect(bustype='socketcan', channel=interface, bitrate=baudrate)

    try:
        # Step 1 - Read current SW ID
        try:
            swid = flash_node.sdo[H1F56_PROGRAM_SWID][PROGRAM_NUMBER].raw
            print(f"\n[1/6] Current SW ID: 0x{swid:08x}")
        except Exception:
            print("\n[1/6] Could not read current SW ID")

        # Step 2 - Wait for flash status
        print("[2/6] Waiting for flash status...")
        status = wait_for_flash_status_ok(flash_node, timeout=DEFAULT_TIMEOUT)
        if status != 0:
            print(f"      Warning: flash status 0x{status:08x}")

        # Step 3 - Enter pre-operational
        print("[3/6] Entering pre-operational mode...")
        flash_node.nmt.state = 'PRE-OPERATIONAL'

        # Step 4 - Stop program
        print("[4/6] Stopping program...")
        flash_node.sdo[H1F51_PROGRAM_CTRL][PROGRAM_NUMBER].raw = PROGRAM_CTRL_STOP

        # Step 5 - Clear program
        print("[5/6] Clearing program (this may take a few seconds)...")
        flash_node.sdo[H1F51_PROGRAM_CTRL][PROGRAM_NUMBER].raw = PROGRAM_CTRL_CLEAR
        status = wait_for_flash_status_ok(flash_node, timeout=DEFAULT_TIMEOUT)
        if status != 0:
            raise ValueError(f"Flash clear failed: status 0x{status:08x}")
        print("      Flash cleared OK")

        # Step 6 - Download firmware
        print("[6/6] Downloading firmware...")
        bin_size = os.path.getsize(bin_path)
        bar_width = 40
        total_sent = 0

        with open(bin_path, 'rb') as infile:
            with flash_node.sdo[H1F50_PROGRAM_DATA][PROGRAM_NUMBER].open(
                'wb', buffering=DEFAULT_BUFFER_SIZE, size=bin_size, block_transfer=True
            ) as outfile:
                while True:
                    chunk = infile.read(DEFAULT_BUFFER_SIZE // 2)
                    if not chunk:
                        break
                    outfile.write(chunk)
                    total_sent += len(chunk)
                    percent = total_sent / bin_size
                    filled = int(bar_width * percent)
                    bar = "#" * filled + "-" * (bar_width - filled)
                    print(f"\r {percent*100:.1f}% [{bar}] {total_sent}/{bin_size}B", end="", flush=True)
        print()

        status = wait_for_flash_status_ok(flash_node, timeout=DEFAULT_TIMEOUT)
        if status != 0:
            raise ValueError(f"Firmware download failed: status 0x{status:08x}")
        print("      Download OK")

        # Read new SW ID
        try:
            swid = flash_node.sdo[H1F56_PROGRAM_SWID][PROGRAM_NUMBER].raw
            print(f"      New SW ID: 0x{swid:08x}")
        except Exception:
            pass

        # Start program
        print("      Starting program (waiting for boot-up)...")
        flash_node.sdo[H1F51_PROGRAM_CTRL][PROGRAM_NUMBER].raw = PROGRAM_CTRL_START
        try:
            flash_node.nmt.wait_for_bootup(timeout=DEFAULT_TIMEOUT)
            print("      Boot-up received OK")
        except Exception:
            print("      Warning: no boot-up message received within timeout")

        # Confirm program
        print("      Entering pre-operational mode...")
        flash_node.nmt.state = 'PRE-OPERATIONAL'
        print("      Confirming program...")
        flash_node.sdo[H1F51_PROGRAM_CTRL][PROGRAM_NUMBER].raw = PROGRAM_CTRL_CONFIRM

        print("\nFirmware update completed successfully!")

    finally:
        network.disconnect()


def parse_args():
    parser = argparse.ArgumentParser(
        description="CANopen firmware update tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python co-firmware-update.py --node-id 1 --bin build/zephyr/zephyr.signed.bin
  python co-firmware-update.py --node-id 1 --bin build/zephyr/zephyr.signed.bin --interface can0 --baudrate 500000
        """,
    )
    parser.add_argument("--node-id", type=int, required=True,
                        help="CANopen node ID of the target device")
    parser.add_argument("--bin", required=True, dest="bin_path",
                        help="Path to the signed firmware binary (zephyr.signed.bin)")
    parser.add_argument("--interface", default=None,
                        help="CAN interface (overrides co-firmware-update.yaml)")
    parser.add_argument("--baudrate", type=int, default=None,
                        help="CAN baudrate (overrides co-firmware-update.yaml)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt")
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()

    interface = args.interface or config.get("interface")
    baudrate  = args.baudrate  or config.get("baudrate")

    if not interface:
        print("Error: 'interface' not set. Provide --interface or set it in co-firmware-update.yaml")
        sys.exit(1)

    if not baudrate:
        print("Error: 'baudrate' not set. Provide --baudrate or set it in co-firmware-update.yaml")
        sys.exit(1)

    bin_path = os.path.abspath(args.bin_path)
    if not os.path.isfile(bin_path):
        print(f"Error: firmware file not found: {bin_path}")
        sys.exit(1)

    bin_size = os.path.getsize(bin_path)

    print(f"\nFirmware update")
    print(f"  Node ID   : {args.node_id}")
    print(f"  Binary    : {os.path.basename(bin_path)} ({bin_size} bytes)")
    print(f"  Interface : {interface}")
    print(f"  Baudrate  : {baudrate}")

    if not args.yes:
        confirm = input("\nProceed with firmware update? (y/N): ").strip().lower()
        if confirm != "y":
            print("Firmware update cancelled.")
            sys.exit(0)

    print()

    try:
        flash_firmware(
            node_id=args.node_id,
            bin_path=bin_path,
            interface=interface,
            baudrate=baudrate,
        )
    except Exception as e:
        print(f"\nFirmware update failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
