# CAN TCP Bridge

This directory contains a simple **CAN ↔ TCP bridge** composed of two components:

- **can-tcp-bridge-server**: runs on the host PC and exposes a TCP server connected to a CAN interface.
- **can-tcp-bridge-client**: runs on an ESP32 and forwards CAN frames between the ESP32 CAN interface and the TCP server.

Together they allow a **remote CAN bus to be accessed over TCP/IP**.

---

## Getting started

If you need detailed information about the setup you can take a look at the [Zephyr Getting Started](https://docs.zephyrproject.org/latest/getting_started/index.html) documentation.

### Prerequisites

Install the required tools:

```bash
sudo apt install -y minicom can-utils
```

---
## Configure the Client

Edit the following file:

```
can-tcp-bridge-client/prj.conf
```

Set your WiFi credentials and the IP address of the machine running the server.

Example:

```c
# Application
CONFIG_APP_WIFI_SSID="YOUR_WIFI_SSID"
CONFIG_APP_WIFI_PASSWORD="YOUR_WIFI_PASSWORD"
CONFIG_APP_SERVER_HOST="YOUR_PC_IP_ADDRESS"
CONFIG_APP_SERVER_PORT=50000
```

---

### Build and Flash the ESP32 as Client

Build the firmware:

```bash
cd can-tcp-bridge/
west build -b esp32_devkitc/esp32/procpu can-tcp-bridge-client
```

Flash the ESP32:

```bash
west flash
```

---

### Create a Virtual CAN Interface (Host PC)

Create and set up a virtual CAN interface on the host machine:

```bash
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Verify the interface is up and running:

```bash
ifconfig
```

You should see something similar to:

```bash
vcan0: flags=193<UP,RUNNING,NOARP>  mtu 72
        unspec 00-00-00-00-00-00-00-00-00-00-00-00-00-00-00-00  txqueuelen 1000  (UNSPEC)
        RX packets 0  bytes 0 (0.0 KB)
        RX errors 0  dropped 0  overruns 0  frame 0
        TX packets 0  bytes 0 (0.0 KB)
        TX errors 0  dropped 0 overruns 0  carrier 0  collisions 0
```

---

### Test the Virtual CAN Interface

Open two terminals, then on the first one:

#### Terminal 1

```bash
candump vcan0
```

#### Terminal 2

```bash
cansend vcan0 123#DEADBEEF
```

If everything is working correctly, the `123#DEADBEEF` should appear in the first terminal.

---

### Run the CAN TCP Bridge Server

Run the server script:

```bash
cd can-tcp-bridge-server/
python can_tcp_bridge.py -c config.yaml -v
```

Example output:

```bash
YYYY-MM-DD HH:MM:SS [INFO] bridge: Opened CAN bus on vcan0
YYYY-MM-DD HH:MM:SS [INFO] bridge: Server listening on 0.0.0.0:50000 ...
YYYY-MM-DD HH:MM:SS [INFO] bridge: Accepted peer 192.168.1.100
```

This means the ESP32 client successfully connected to the server.

---

### Monitor the ESP32 Logs

Connect to the ESP32 serial port:

```bash
minicom -D /dev/ttyUSB0 -b 115200
```
> NOTE: The device `/dev/ttyUSB0` might has a different name on your computer.

Example output:

```bash
*** Booting Zephyr OS build ***
[HH:MM:SS] <inf> connection_manager: WIFI try connecting...
[HH:MM:SS] <inf> connection_manager: Connection successful
[HH:MM:SS] <inf> app: Connecting to 192.168.1.100:50000 ...
[HH:MM:SS] <inf> app: TCP connected
[HH:MM:SS] <inf> app: Bridge running: CAN <-> TCP
```

---

This confirms that the **CAN ↔ TCP bridge is working correctly**.
