import os
import time
import math
import threading
import urllib.request
import urllib.error
import urllib.parse
import json
import csv
import sys
import tkinter as tk
import socket
import uuid
import hashlib
import ctypes
from tkinter import messagebox

def verify_and_preload_simconnect():
    # Only protect when running as an executable where the DLL is bundled in _MEIPASS
    if not getattr(sys, 'frozen', False):
        return
        
    EXPECTED_HASH = "677fd3849d54e2a6831dc1aa348d974ead2255ec609fbf5830ef32bf0804b8bc"
    meipass = getattr(sys, '_MEIPASS', '')
    safe_dll = os.path.join(meipass, "SimConnect.dll")
    
    if not os.path.exists(safe_dll):
        return
        
    # Verify hash to prevent internal _MEIPASS tampering
    try:
        with open(safe_dll, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        if file_hash != EXPECTED_HASH:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Security Threat Detected", "SimConnect.dll hash mismatch!\n\nExecution aborted to prevent DLL sideloading/hijacking attack.")
            sys.exit(1)
            
        # Pre-load the verified absolute path.
        # This prevents python-simconnect from searching CWD when it calls windll.LoadLibrary('SimConnect.dll')
        # Windows will see 'SimConnect.dll' is already loaded in memory and use our safe, verified version.
        ctypes.WinDLL(safe_dll)
    except Exception as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Security Error", f"Failed to verify SimConnect DLL: {e}")
        sys.exit(1)

verify_and_preload_simconnect()

try:
    from SimConnect import SimConnect, AircraftRequests
except ImportError:
    SimConnect = None
    AircraftRequests = None

def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0 # Earth radius in kilometers
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class MSFSClientConfigFile:
    def __init__(self, filename="client_config.json"):
        self.filename = os.path.join(get_base_path(), filename)
        
    def save(self, magic_code):
        with open(self.filename, 'w') as f:
            json.dump({"magic_code": magic_code}, f)
            
    def load(self):
        try:
            with open(self.filename, 'r') as f:
                return json.load(f).get("magic_code", "")
        except:
            return ""

class ClientApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SimRadio MSFS Client")
        self.root.geometry("400x250")
        self.root.resizable(False, False)
        
        self.config_manager = MSFSClientConfigFile()
        self.connected = False
        self.run_loop = False
        self.sm = None
        self.aq = None
        self.client_id = str(uuid.uuid4())
        
        self.facilities_cache = []
        
        # Header Label
        tk.Label(self.root, text="SimRadio Client", font=("Arial", 16, "bold")).pack(pady=10)
        
        # Magic Code Entry
        tk.Label(self.root, text="Discord Magic Code:", font=("Arial", 10)).pack()
        self.code_entry = tk.Entry(self.root, width=40, font=("Arial", 10), justify="center")
        self.code_entry.pack(pady=5)
        self.code_entry.insert(0, self.config_manager.load())
        
        # Connect Button
        self.connect_btn = tk.Button(self.root, text="Connect to MSFS & Server", command=self.toggle_connection, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), width=30)
        self.connect_btn.pack(pady=15)
        
        # Status Label
        self.status_var = tk.StringVar()
        self.status_var.set("Status: Disconnected")
        self.status_label = tk.Label(self.root, textvariable=self.status_var, font=("Arial", 10), fg="grey")
        self.status_label.pack(pady=5)
        
        # Load airports in background
        threading.Thread(target=self._load_airports, daemon=True).start()
        
    def _load_airports(self):
        self.status_var.set("Status: Loading Airports Database...")
        airports_file = os.path.join(get_base_path(), "airports.csv")
        if not os.path.exists(airports_file):
            try:
                urllib.request.urlretrieve("https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv", airports_file)
            except Exception as e:
                self.status_var.set(f"Error downloading airports: {e}")
                return
                
        try:
            with open(airports_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader) # skip header
                for row in reader:
                    if len(row) < 6:
                        continue
                    ident = row[1]
                    atype = row[2]
                    if atype in ["closed", "heliport", "seaplane_base"]:
                        continue
                    try:
                        self.facilities_cache.append({
                            "icao_4char": ident,
                            "lat": float(row[4]),
                            "lon": float(row[5])
                        })
                    except ValueError:
                        continue
            if not self.connected:
                self.status_var.set(f"Airports Loaded. Ready to connect.")
        except Exception as e:
            self.status_var.set(f"Error reading airports database.")

    def toggle_connection(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()
            
    def _connect(self):
        magic_code = self.code_entry.get().strip()
        if not magic_code or "-" not in magic_code:
            messagebox.showerror("Error", "Invalid magic code format. Be sure to paste the exact link code.")
            return
            
        if not SimConnect:
            messagebox.showerror("Error", "SimConnect.dll or library missing. Run pip install SimConnect.")
            return
            
        try:
            self.status_var.set("Status: Attaching to MSFS...")
            self.root.update()
            self.sm = SimConnect()
            # ok is only set True when MSFS sends its handshake acknowledgement back.
            # If it's still False here, the sim isn't running even though no exception was raised.
            if not self.sm.ok:
                raise ConnectionError("SimConnect opened but MSFS did not respond. Is the simulator running?")
            self.aq = AircraftRequests(self.sm, _time=200)
        except Exception as e:
            messagebox.showerror("Error", f"Could not connect to MSFS.\nMake sure Microsoft Flight Simulator is running before connecting.\n\nDetail: {e}")
            self.status_var.set("Status: Disconnected")
            self.status_label.config(fg="grey")
            self.sm = None
            return
            
        self.config_manager.save(magic_code)
        
        server_url, token = magic_code.rsplit("-", 1)
        self.server_url = f"{server_url}/update_state"
        self.token = token
        
        self.connected = True
        self.run_loop = True
        self.connect_btn.config(text="Disconnect", bg="#f44336")
        self.status_var.set("Status: Actively Broadcasting to Server")
        self.status_label.config(fg="green")
        
        threading.Thread(target=self._polling_loop, daemon=True).start()
        
    def _disconnect(self):
        self.run_loop = False
        if self.sm:
            try:
                self.sm.exit()  # Properly signals SimConnect to close the handle
            except: pass
        self.sm = None
        self.connected = False
        self.connect_btn.config(text="Connect to MSFS & Server", bg="#4CAF50")
        self.status_var.set("Status: Disconnected")
        self.status_label.config(fg="grey")

    def _handle_msfs_disconnect(self):
        self._disconnect()
        messagebox.showerror("MSFS Disconnected", "Connection to Microsoft Flight Simulator was lost. Make sure the game is running.")

    def _update_closest_airport(self, cur_lat, cur_lon):
        if not self.facilities_cache: return None
        if abs(cur_lat) < 1.0 and abs(cur_lon) < 1.0: return None
            
        closest_distance = float('inf')
        closest_facility = None
        for fac in self.facilities_cache:
            dist = haversine(cur_lat, cur_lon, fac["lat"], fac["lon"])
            if dist < closest_distance:
                closest_distance = dist
                closest_facility = fac
        return closest_facility["icao_4char"] if closest_facility else None

    def _polling_loop(self):
        last_request_time = 0
        while self.run_loop:
            current_time = time.time()
            if current_time - last_request_time >= 5.0:
                try:
                    # Natively detect if MSFS sent a graceful shutdown signal
                    if self.sm and self.sm.quit != 0:
                        raise OSError("MSFS gracefull quit signal received.")
                    
                    com1 = self.aq.get("COM_ACTIVE_FREQUENCY:1")
                    lat = self.aq.get("PLANE_LATITUDE")
                    lon = self.aq.get("PLANE_LONGITUDE")
                    
                    if com1 is not None and lat is not None and lon is not None:
                        c_com1, c_lat, c_lon = float(com1), float(lat), float(lon)
                        icao = self._update_closest_airport(c_lat, c_lon)
                        
                        payload = json.dumps({
                            "token": self.token,
                            "client_id": self.client_id,
                            "lat": c_lat,
                            "lon": c_lon,
                            "com1": c_com1,
                            "closest_icao_4char": icao
                        }).encode("utf-8")
                        
                        req = urllib.request.Request(self.server_url, data=payload, headers={'Content-Type': 'application/json'})
                        urllib.request.urlopen(req, timeout=3)
                        
                        # Fix UI if connection restores
                        if self.status_var.get() != "Status: Actively Broadcasting to Server":
                            self.status_var.set("Status: Actively Broadcasting to Server")
                            self.status_label.config(fg="green")
                        
                except urllib.error.HTTPError as e:
                    if e.code == 401:
                        self.status_var.set("Status: Session Expired - Please create a new link")
                        self.status_label.config(fg="red")
                    elif e.code == 409:
                        try:
                            # Try to extract the error description.
                            body = e.read().decode('utf-8')
                            msg = json.loads(body).get("error", "Another client is already broadcasting with this magic code.")
                        except Exception:
                            msg = "Another client is already broadcasting with this magic code."
                        self.run_loop = False
                        self.root.after(0, lambda m=msg: messagebox.showerror("Conflict Error", m))
                        self.root.after(0, self._disconnect)
                        break
                    else:
                        self.status_var.set("Status: Server Offline - Retrying...")
                        self.status_label.config(fg="#ff9800")
                except urllib.error.URLError:
                    self.status_var.set("Status: Server Offline - Retrying...")
                    self.status_label.config(fg="#ff9800")
                except Exception as e:
                    # Ignore MSFS transient errors, but catch full pipe breaks (OSError)
                    if isinstance(e, OSError) or "pipe" in str(e).lower() or "simconnect" in str(type(e)).lower():
                        self.run_loop = False
                        self.root.after(0, self._handle_msfs_disconnect)
                        break
                last_request_time = current_time
            time.sleep(0.1)

def check_single_instance():
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _lock_socket.bind(("127.0.0.1", 47332)) # Fixed port for a local lock
    except OSError:
        # Hide the empty root creation that tk.messagebox will trigger if we have no root.
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Instance Error", "Another instance of SimRadio Client is already running locally.")
        sys.exit(1)

if __name__ == "__main__":
    check_single_instance()
    app = ClientApp()
    app.root.mainloop()
