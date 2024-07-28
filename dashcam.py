import os
import time
import shutil
import psutil
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
import subprocess
import logging
import threading

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
VIDEO_LENGTH = 60  # Default length in seconds, adjustable via dashboard
VIDEO_PATH = '/home/dashcam/videos'  # Change path accordingly
THRESHOLD = 80  # Percentage for storage management
HOTSPOT_INTERFACE = 'wlan0'
HOTSPOT_SSID = 'Dashcam'
HOTSPOT_PASSWORD = 'dash@123'
APP_PORT = 5000

# Create directory if not exists
if not os.path.exists(VIDEO_PATH):
    os.makedirs(VIDEO_PATH)

def get_filename():
    now = datetime.now()
    return now.strftime('%d-%m-%Y-%H-%M-%S.mp4')

def record_video(duration=VIDEO_LENGTH):
    filename = os.path.join(VIDEO_PATH, get_filename())
    cmd = f"libcamera-vid -t {duration * 1000} -o {filename} --width 1920 --height 1080"
    logging.debug(f"Executing command: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
        logging.info(f"Video recorded successfully: {filename}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to record video: {e}")

def get_disk_usage():
    total, used, free = shutil.disk_usage('/')
    return (used / total) * 100

def delete_oldest_file():
    files = [os.path.join(VIDEO_PATH, f) for f in os.listdir(VIDEO_PATH)]
    files = [f for f in files if os.path.isfile(f)]
    oldest_file = min(files, key=os.path.getctime)
    os.remove(oldest_file)
    logging.info(f"Deleted oldest file: {oldest_file}")

def manage_storage():
    while get_disk_usage() > THRESHOLD:
        delete_oldest_file()

def get_videos():
    return sorted([f for f in os.listdir(VIDEO_PATH) if f.endswith('.mp4')])

def get_system_info():
    try:
        temperatures = psutil.sensors_temperatures()
        cpu_temp = temperatures['cpu-thermal'][0].current if 'cpu-thermal' in temperatures else None
    except Exception as e:
        logging.error(f"Failed to get system info: {e}")
        cpu_temp = None
    return {
        'temperature': cpu_temp,
        'disk_usage': psutil.disk_usage('/').percent,
        'video_count': len(get_videos())
    }

def setup_hotspot():
    try:
        os.system(f"""
        sudo systemctl stop hostapd
        sudo systemctl stop dnsmasq
        sudo bash -c 'cat > /etc/hostapd/hostapd.conf <<- EOM
        interface={HOTSPOT_INTERFACE}
        driver=nl80211
        ssid={HOTSPOT_SSID}
        hw_mode=g
        channel=7
        wmm_enabled=0
        macaddr_acl=0
        auth_algs=1
        ignore_broadcast_ssid=0
        wpa=2
        wpa_passphrase={HOTSPOT_PASSWORD}
        wpa_key_mgmt=WPA-PSK
        rsn_pairwise=CCMP
        EOM'
        sudo bash -c 'cat > /etc/dnsmasq.conf <<- EOM
        interface={HOTSPOT_INTERFACE}
        dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
        EOM'
        sudo systemctl start hostapd
        sudo systemctl start dnsmasq
        """)
        logging.info("Hotspot setup completed.")
    except Exception as e:
        logging.error(f"Failed to setup hotspot: {e}")

def start_hotspot_if_not_connected():
    try:
        if not psutil.net_if_stats()[HOTSPOT_INTERFACE].isup:
            setup_hotspot()
    except Exception as e:
        logging.error(f"Failed to start hotspot: {e}")

# Flask app
app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html', videos=get_videos(), system_info=get_system_info())

@app.route('/settings', methods=['POST'])
def settings():
    global VIDEO_LENGTH
    try:
        VIDEO_LENGTH = int(request.form['video_length'])
        return jsonify(status='success', video_length=VIDEO_LENGTH)
    except ValueError as e:
        logging.error(f"Invalid video length: {e}")
        return jsonify(status='error', message='Invalid video length')

@app.route('/videos/<filename>')
def video(filename):
    return send_from_directory(VIDEO_PATH, filename)

@app.route('/stream')
def stream():
    # Implement streaming functionality
    pass

def recording_task():
    while True:
        try:
            record_video()
            manage_storage()
            time.sleep(1)  # Ensure there is a small delay to handle next recording properly
        except Exception as e:
            logging.error(f"Error in recording task: {e}")

if __name__ == '__main__':
    try:
        # Start the recording task in a separate thread
        recording_thread = threading.Thread(target=recording_task, daemon=True)
        recording_thread.start()
        
        # Start hotspot if not connected
        start_hotspot_if_not_connected()
        
        app.run(host='0.0.0.0', port=APP_PORT)
    except Exception as e:
        logging.error(f"Failed to start the application: {e}")
