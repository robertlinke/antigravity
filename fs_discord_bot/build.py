import os
import subprocess
import sys

def build():
    print("Installing requirements...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    # Dynamically locate the SimConnect Windows DLL
    import SimConnect
    dll_path = os.path.join(os.path.dirname(SimConnect.__file__), "SimConnect.dll")
    print(f"\nFound native DLL at: {dll_path}")
    
    print("\nBuilding Executable...")
    # Client Build: hides the black terminal window so you only see the minimal GUI
    command_client = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--add-binary", f"{dll_path};SimConnect",
        "--name", "SimRadioClient",
        "client.py"
    ]
    
    # Server Build: keeps the debug console for logs
    command_server = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "SimRadioServer",
        "server.py"
    ]
    
    try:
        print("Building SimRadioClient.exe...")
        subprocess.check_call(command_client)
        print("Building SimRadioServer.exe...")
        subprocess.check_call(command_server)
        print("\n[+] Build complete! You can find BOTH executables inside the 'dist' folder.")
    except Exception as e:
        print(f"\n[-] Build failed: {e}")

if __name__ == "__main__":
    build()
