#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# CAN <-> TCP Bridge
# ------------------
# Bridge CAN frames over TCP between two machines running this same script.
# Configurable via YAML. Works on Ubuntu and Raspberry Pi OS with SocketCAN.
#
# Usage:
#   python can_tcp_bridge.py -c config.yaml -v
#
# Requires: python-can, PyYAML

import argparse
import logging
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import yaml
from typing import Optional

try:
    import can
except ImportError:
    print("Missing dependency 'python-can'. Install with: pip install python-can", file=sys.stderr)
    raise

# ----------------------------- Configuration Model -----------------------------

DEFAULT_CONFIG = {
    "role": "server",                 # "server" or "client"
    "bind_host": "0.0.0.0",           # Used by server
    "port": 50000,                    # Used by server & client
    "peer_host": "127.0.0.1",         # Used by client
    "peer_port": 50000,               # Used by client
    "tcp_keepalive": True,
    "reconnect_delay_sec": 2.0,       # Base delay for TCP reconnects (client) or waiting (server)
    "can": {
        "iface": "vcan0",
        "bitrate": 250000,            # Ignored for vcan; used if bringup=true
        "fd": False,                  # Enable FD (requires kernel & iface support)
        "data_bitrate": 2000000,      # Only for CAN FD (BRS), optional
        "brs": False,                 # Use bitrate switch when sending FD frames
        "bringup": False,             # If true, bring the iface up with iproute2
        "restart_ms": 100,            # CAN controller auto restart (ms), optional
    }
}

# ----------------------------- Utilities -----------------------------

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Merge with defaults shallowly
    def merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict):
                node = dst.setdefault(k, {})
                merge(node, v)
            else:
                dst.setdefault(k, v)
        return dst
    return merge(cfg, DEFAULT_CONFIG)


def bring_up_interface(can_cfg: dict, logger: logging.Logger) -> None:
    """Optionally bring up SocketCAN interface with bitrate using iproute2.
    Requires root privileges. Safe to call if already up.
    """
    iface = can_cfg.get("iface", "can0")
    bringup = bool(can_cfg.get("bringup", False))
    bitrate = int(can_cfg.get("bitrate", 250000))
    restart_ms = can_cfg.get("restart_ms")
    use_fd = bool(can_cfg.get("fd", False))
    data_bitrate = int(can_cfg.get("data_bitrate", 0))
    if not bringup:
        logger.info("Skipping interface bring-up (bringup=false): %s", iface)
        return

    if os.geteuid() != 0:
        logger.warning("Interface bring-up requested but not running as root; skipping ip link setup.")
        return

    def run(cmd):
        logger.debug("Running: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            logger.debug("Command failed (ignored): %s\n%s", " ".join(cmd), e.stderr.decode(errors="ignore"))

    run(["ip", "link", "set", iface, "down"])

    if use_fd:
        cmd = ["ip", "link", "set", iface, "type", "can", "bitrate", str(bitrate),
               "dbitrate", str(data_bitrate or 2000000), "fd", "on"]
    else:
        cmd = ["ip", "link", "set", iface, "type", "can", "bitrate", str(bitrate)]

    if restart_ms:
        cmd += ["restart-ms", str(int(restart_ms))]

    run(cmd)
    run(["ip", "link", "set", iface, "up"])
    logger.info("Interface %s brought up (bitrate=%s, fd=%s).", iface, bitrate, use_fd)


def make_bus(can_cfg: dict) -> "can.Bus":
    iface = can_cfg.get("iface", "vcan0")
    use_fd = bool(can_cfg.get("fd", False))
    bus = can.Bus(channel=iface, interface="socketcan", fd=use_fd)
    return bus


def set_tcp_keepalive(sock: socket.socket) -> None:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

# ----------------------------- TCP Framing -----------------------------
# Record: [2B length][4B can_id][1B flags][1B data_len][data...]
_RECORD_HDR = struct.Struct("!H I B B")   # sender uses this (includes length)
_HDR_NO_LEN = struct.Struct("!I B B")      # receiver uses this (no length)

FLAG_EXT = 1 << 0
FLAG_RTR = 1 << 1
FLAG_FD  = 1 << 2
FLAG_BRS = 1 << 3

def frame_from_can(msg: "can.Message", use_fd_cfg: bool) -> bytes:
    flags = 0
    if msg.is_extended_id:
        flags |= FLAG_EXT
    if msg.is_remote_frame:
        flags |= FLAG_RTR
    if getattr(msg, "is_fd", False) or use_fd_cfg:
        flags |= FLAG_FD
        if getattr(msg, "bitrate_switch", False):
            flags |= FLAG_BRS

    data = bytes(msg.data) if msg.data is not None else b""
    n = len(data)
    if n > 64:
        raise ValueError("Data length exceeds 64 bytes")
    payload = _RECORD_HDR.pack(6 + n, msg.arbitration_id & 0x1FFFFFFF, flags, n) + data
    return payload

def can_from_frame(buf: bytes) -> "can.Message":
    """Convert a TCP payload (already stripped of the 2-byte length) into a python-can Message."""
    if len(buf) < _HDR_NO_LEN.size:
        raise ValueError("short frame header")
    can_id, flags, n = _HDR_NO_LEN.unpack_from(buf, 0)
    if n > 64:
        raise ValueError("invalid DLC (>64)")
    if len(buf) < _HDR_NO_LEN.size + n:
        raise ValueError("short frame body")
    data = buf[_HDR_NO_LEN.size:_HDR_NO_LEN.size + n]

    is_extended_id = bool(flags & FLAG_EXT)
    is_remote = bool(flags & FLAG_RTR)
    is_fd = bool(flags & FLAG_FD)
    brs = bool(flags & FLAG_BRS)

    msg = can.Message(
        arbitration_id=can_id,
        is_extended_id=is_extended_id,
        is_remote_frame=is_remote,
        data=data,
        is_fd=is_fd,
        bitrate_switch=brs,
    )
    return msg

class TCPFramer:
    """Incremental TCP framer to parse length-prefixed records."""
    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes):
        self._buf.extend(chunk)

    def next_record(self) -> Optional[bytes]:
        if len(self._buf) < 2:
            return None
        (length,) = struct.unpack_from("!H", self._buf, 0)
        total = 2 + length
        if len(self._buf) < total:
            return None
        rec = bytes(self._buf[2:total])
        del self._buf[:total]
        return rec

# ----------------------------- Bridge Threads -----------------------------

class Bridge:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.logger = logging.getLogger("bridge")
        self.stop_event = threading.Event()
        self.sock_lock = threading.Lock()
        self.sock: Optional[socket.socket] = None
        self.bus: Optional[can.Bus] = None

    def start(self):
        bring_up_interface(self.cfg["can"], self.logger)
        self.bus = make_bus(self.cfg["can"])
        self.logger.info("Opened CAN bus on %s", self.cfg["can"]["iface"])

        t = threading.Thread(target=self._tcp_manager, name="tcp-manager", daemon=True)
        t.start()

        self._loop_can_to_tcp()

    def stop(self):
        self.stop_event.set()
        try:
            if self.sock:
                self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        try:
            if self.bus:
                self.bus.shutdown()
        except Exception:
            pass

    def _tcp_manager(self):
        role = self.cfg.get("role", "server")
        delay = float(self.cfg.get("reconnect_delay_sec", 2.0))
        while not self.stop_event.is_set():
            try:
                if role == "server":
                    self._accept_once()
                else:
                    self._connect_once()
                self._loop_tcp_to_can()
            except Exception as e:
                self.logger.warning("TCP path ended: %s", e)
            with self.sock_lock:
                if self.sock:
                    try:
                        self.sock.close()
                    except Exception:
                        pass
                    self.sock = None
            for _ in range(int(delay * 10)):
                if self.stop_event.is_set():
                    break
                time.sleep(0.1)

    def _accept_once(self):
        host = self.cfg.get("bind_host", "0.0.0.0")
        port = int(self.cfg.get("port", 50000))
        self.logger.info("Server listening on %s:%d ...", host, port)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(1)
            srv.settimeout(2.0)
            while not self.stop_event.is_set():
                try:
                    conn, addr = srv.accept()
                    self.logger.info("Accepted peer %s:%d", addr[0], addr[1])
                    if self.cfg.get("tcp_keepalive", True):
                        set_tcp_keepalive(conn)
                    conn.settimeout(None)
                    with self.sock_lock:
                        if self.sock:
                            try:
                                self.sock.close()
                            except Exception:
                                pass
                        self.sock = conn
                    return
                except socket.timeout:
                    continue

    def _connect_once(self):
        host = self.cfg.get("peer_host", "127.0.0.1")
        port = int(self.cfg.get("peer_port", int(self.cfg.get("port", 50000))))
        self.logger.info("Client connecting to %s:%d ...", host, port)
        while not self.stop_event.is_set():
            try:
                conn = socket.create_connection((host, port), timeout=5.0)
                self.logger.info("Connected to %s:%d", host, port)
                if self.cfg.get("tcp_keepalive", True):
                    set_tcp_keepalive(conn)
                conn.settimeout(None)
                with self.sock_lock:
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception:
                            pass
                    self.sock = conn
                return
            except OSError as e:
                self.logger.warning("Connect failed: %s; retrying ...", e)
                time.sleep(float(self.cfg.get("reconnect_delay_sec", 2.0)))

    def _loop_can_to_tcp(self):
        assert self.bus is not None
        use_fd_cfg = bool(self.cfg["can"].get("fd", False))
        while not self.stop_event.is_set():
            try:
                msg = self.bus.recv(timeout=0.2)  # type: ignore
                if msg is None:
                    continue
                payload = frame_from_can(msg, use_fd_cfg)
                with self.sock_lock:
                    s = self.sock
                if s:
                    try:
                        s.sendall(payload)
                    except OSError as e:
                        self.logger.warning("TCP send failed: %s", e)
                self.logger.debug("CAN->TCP  id=0x%08X dlc=%d ext=%d fd=%d",
                                  msg.arbitration_id, len(msg.data or b""), msg.is_extended_id, getattr(msg, "is_fd", False))
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error("Error in CAN->TCP loop: %s", e)

        self.logger.info("CAN->TCP loop terminated.")

    def _loop_tcp_to_can(self):
        assert self.bus is not None
        framer = TCPFramer()
        while not self.stop_event.is_set():
            with self.sock_lock:
                s = self.sock
            if not s:
                break
            try:
                chunk = s.recv(4096)
                if not chunk:
                    raise ConnectionError("Peer closed")
                framer.feed(chunk)
                while True:
                    rec = framer.next_record()
                    if rec is None:
                        break
                    try:
                        msg = can_from_frame(rec)
                        self.bus.send(msg)
                        self.logger.debug("TCP->CAN id=0x%08X dlc=%d ext=%d fd=%d",
                                          msg.arbitration_id, len(msg.data or b""), msg.is_extended_id, getattr(msg, "is_fd", False))
                    except can.CanError as e:
                        self.logger.warning("CAN send failed: %s", e)
            except (OSError, ConnectionError) as e:
                self.logger.warning("TCP receive ended: %s", e)
                break
            except Exception as e:
                self.logger.error("Error in TCP->CAN loop: %s", e)
                break
        self.logger.info("TCP->CAN loop ended; waiting for reconnection.")

# ----------------------------- CLI -----------------------------

def main():
    parser = argparse.ArgumentParser(description="CAN <-> TCP bridge with YAML configuration.")
    parser.add_argument("-c", "--config", required=True, help="Path to YAML config file")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bridge = Bridge(cfg)

    try:
        bridge.start()
    except KeyboardInterrupt:
        print("\nInterrupted, stopping ...")
    finally:
        bridge.stop()

if __name__ == "__main__":
    main()
