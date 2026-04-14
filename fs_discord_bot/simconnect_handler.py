import os
import time
import math
import threading
import urllib.request
import csv

try:
    from SimConnect import SimConnect, AircraftRequests
except ImportError:
    SimConnect = None
    AircraftRequests = None

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0 # Earth radius in kilometers
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class MSFSClient:
    def __init__(self):
        self.connected = False
        self.latest_data = {
            "com1": 118.0,
            "lat": 0.0,
            "lon": 0.0,
            "closest_icao": None,
            "closest_icao_4char": None
        }
        self.run_loop = False
        self.sm = None
        self.aq = None
        
        self.facilities_cache = []
        self._load_airports()

    def _load_airports(self):
        airports_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "airports.csv")
        if not os.path.exists(airports_file):
            print("Downloading airports database (~10MB)...")
            try:
                urllib.request.urlretrieve("https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv", airports_file)
            except Exception as e:
                print(f"Failed to download airports DB: {e}")
                return
                
        print("Loading local airports database...")
        try:
            with open(airports_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader) # skip header
                for row in reader:
                    if len(row) < 6:
                        continue
                    # 'id'[0], 'ident'[1], 'type'[2], 'name'[3], 'latitude_deg'[4], 'longitude_deg'[5]
                    ident = row[1]
                    atype = row[2]
                    if atype in ["closed", "heliport", "seaplane_base"]:
                        continue
                    try:
                        lat = float(row[4])
                        lon = float(row[5])
                        self.facilities_cache.append({
                            "icao_4char": ident,
                            "lat": lat,
                            "lon": lon
                        })
                    except ValueError:
                        continue
            print(f"Loaded {len(self.facilities_cache)} airports.")
        except Exception as e:
            print(f"Error reading airports.csv: {e}")

    def start(self):
        if not SimConnect:
            print("Failed to load SimConnect Python Library. Make sure it is installed.")
            return False

        try:
            # Open connection using PyPI SimConnect
            self.sm = SimConnect()
            self.aq = AircraftRequests(self.sm, _time=200) # cache for 200ms
            self.connected = True
        except Exception as e:
            print(f"Failed to connect SimConnect: {e}")
            return False

        self.run_loop = True
        threading.Thread(target=self._poll_simconnect, daemon=True).start()

        return True

    def stop(self):
        self.run_loop = False
        if self.connected and self.sm:
            try:
                self.sm.quit()
            except:
                pass
            self.connected = False

    def _update_closest_airport(self):
        if not self.facilities_cache:
            return
            
        cur_lat = self.latest_data["lat"]
        cur_lon = self.latest_data["lon"]
        
        # Check if we are in the main menu (MSFS defaults to coordinates near 0,0 when no flight is active)
        if abs(cur_lat) < 1.0 and abs(cur_lon) < 1.0:
            self.latest_data["closest_icao"] = None
            self.latest_data["closest_icao_4char"] = None
            return
            
        closest_distance = float('inf')
        closest_facility = None
        
        # Find closest airport
        for fac in self.facilities_cache:
            dist = haversine(cur_lat, cur_lon, fac["lat"], fac["lon"])
            if dist < closest_distance:
                closest_distance = dist
                closest_facility = fac
                
        if closest_facility:
            self.latest_data["closest_icao"] = closest_facility["icao_4char"]
            self.latest_data["closest_icao_4char"] = closest_facility["icao_4char"]

    def _poll_simconnect(self):
        last_request_time = 0
        while self.run_loop:
            if self.connected and self.aq:
                current_time = time.time()
                if current_time - last_request_time >= 5.0:
                    try:
                        com1 = self.aq.get("COM_ACTIVE_FREQUENCY:1")
                        lat = self.aq.get("PLANE_LATITUDE")
                        lon = self.aq.get("PLANE_LONGITUDE")
                        
                        if com1 is not None and lat is not None and lon is not None:
                            self.latest_data["com1"] = float(com1)
                            self.latest_data["lat"] = float(lat)
                            self.latest_data["lon"] = float(lon)
                            self._update_closest_airport()
                    except Exception as e:
                        pass
                    last_request_time = current_time
            time.sleep(0.1)

    def get_status(self):
        return self.latest_data

# Simple test stub
if __name__ == "__main__":
    client = MSFSClient()
    if client.start():
        print("Connected to MSFS! Waiting for data...")
        try:
            while True:
                print(client.get_status())
                time.sleep(5)
        except KeyboardInterrupt:
            client.stop()
    else:
        print("Failed to connect to MSFS. Make sure the game is running.")
