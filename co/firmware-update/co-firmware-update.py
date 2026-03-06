# Standalone CLI script for CANopen firmware update.
# Usage:
#   python co-firmware-update.py --node-id 1 --bin /path/to/zephyr.signed.bin
#   python co-firmware-update.py --node-id 1 --bin /path/to/zephyr.signed.bin --interface can0 --baudrate 500000

import argparse
import os
import subprocess
import sys

DEFAULT_CONFIG = "co-firmware-update.yaml"


def load_config(config_path):
    config = {}
    if os.path.isfile(config_path):
        try:
            import yaml
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
        except ImportError:
            print(f"Warning: PyYAML not installed, ignoring config file {config_path}")
        except Exception as e:
            print(f"Warning: could not read config file {config_path}: {e}")
    return config


def parse_args():
    parser = argparse.ArgumentParser(
        description="CANopen firmware update tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python firmware_update.py --node-id 1 --bin build/zephyr/zephyr.signed.bin
  python firmware_update.py --node-id 1 --bin build/zephyr/zephyr.signed.bin --interface can0 --baudrate 500000
        """,
    )
    parser.add_argument(
        "--node-id",
        type=int,
        required=True,
        help="CANopen node ID of the target device",
    )
    parser.add_argument(
        "--bin",
        required=True,
        dest="bin_path",
        help="Path to the signed firmware binary (zephyr.signed.bin)",
    )
    parser.add_argument(
        "--interface",
        default=None,
        help="CAN interface (overrides config file)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=None,
        help="CAN baudrate (overrides config file)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Load config file
    config = load_config(DEFAULT_CONFIG)

    # Resolve interface and baudrate: CLI > config file
    interface = args.interface or config.get("interface")
    baudrate = args.baudrate or config.get("baudrate")

    if not interface:
        print("Error: 'interface' not set. Provide --interface or set it in the config file.")
        sys.exit(1)

    if not baudrate:
        print("Error: 'baudrate' not set. Provide --baudrate or set it in the config file.")
        sys.exit(1)

    # Validate binary path
    bin_path = os.path.abspath(args.bin_path)
    if not os.path.isfile(bin_path):
        print(f"Error: firmware file not found: {bin_path}")
        sys.exit(1)

    bin_size = os.path.getsize(bin_path)

    # Derive project and build directories from bin path
    # Expected: <project_root>/build/canopen_firmware_update/zephyr/zephyr.signed.bin
    bin_dir = os.path.dirname(bin_path)
    build_dir = os.path.abspath(os.path.join(bin_dir, "../.."))
    project_dir = os.path.abspath(os.path.join(bin_dir, "../../.."))

    print(f"\nFirmware update")
    print(f"  Node ID   : {args.node_id}")
    print(f"  Binary    : {os.path.basename(bin_path)} ({bin_size} bytes)")
    print(f"  Interface : {interface}")
    print(f"  Baudrate  : {baudrate}")
    print(f"  Build dir : {build_dir}")

    if not args.yes:
        confirm = input("\nProceed with firmware update? (y/N): ").strip().lower()
        if confirm != "y":
            print("Firmware update cancelled.")
            sys.exit(0)

    cmd = [
        "west", "flash",
        "--skip-rebuild",
        "--build-dir", build_dir,
        "--domain", "canopen_firmware_update",
        "--runner", "canopen",
    ]

    print(f"\nRunning: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=project_dir)

    if result.returncode == 0:
        print("\nFirmware update completed successfully!")
    else:
        print(f"\nFirmware update failed with return code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
