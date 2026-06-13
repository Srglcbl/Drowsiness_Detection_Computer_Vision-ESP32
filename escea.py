"""
===============================================
DROWSINESS DETECTION FLASK WEB APP
Modern UI with Tailwind CSS
===============================================
"""

from flask import Flask, render_template_string, Response, jsonify
from flask_socketio import SocketIO, emit
import cv2
from ultralytics import YOLO
import time
from datetime import datetime
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'drowsiness_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==========================================
# KONFIGURASI
# ==========================================

MODEL_PATH = 'best (1).pt'
CLOSED_EYE_FRAMES = 10
YAWN_FRAMES = 15
ALARM_COOLDOWN = 5
CONFIDENCE_THRESHOLD = 0.5

CLASS_NAMES = ['mata_buka', 'mata_tutup', 'nguap', 'tidak_nguap']
CLASS_COLORS = {
    'mata_buka': (0, 255, 0),
    'mata_tutup': (0, 0, 255),
    'nguap': (0, 165, 255),
    'tidak_nguap': (0, 255, 255)
}

# ==========================================
# GLOBAL VARIABLES
# ==========================================

camera = None
model = None
detection_active = False
update_lock = threading.Lock()

status_data = {
    'closed_eye_counter': 0,
    'yawn_counter': 0,
    'fps': 0,
    'current_status': 'NORMAL',
    'session_time': '00:00:00',
    'blink_frequency': 18,
    'last_incident': {'status': 'Belum Ada', 'time': '-'},
    'system_online': True,
    'camera_active': False
}

incident_history = []
session_start_time = None
last_status_emit = 0

# ==========================================
# DRAWING FUNCTIONS
# ==========================================

def draw_progress_bars(frame, closed_counter, yawn_counter):
    height, width = frame.shape[:2]
    
    # Mata tertutup
    bar_y_closed = height - 110
    bar_max_width = 350
    bar_width_closed = int((closed_counter / CLOSED_EYE_FRAMES) * bar_max_width)
    bar_width_closed = min(bar_width_closed, bar_max_width)
    
    cv2.rectangle(frame, (15, bar_y_closed), (15 + bar_max_width, bar_y_closed + 25), (80, 80, 80), -1)
    cv2.rectangle(frame, (15, bar_y_closed), (15 + bar_width_closed, bar_y_closed + 25), (0, 0, 255), -1)
    cv2.rectangle(frame, (15, bar_y_closed), (15 + bar_max_width, bar_y_closed + 25), (200, 200, 200), 2)
    cv2.putText(frame, f'Mata Tertutup: {closed_counter}/{CLOSED_EYE_FRAMES}', 
                (15, bar_y_closed - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    # Menguap
    bar_y_yawn = height - 70
    bar_width_yawn = int((yawn_counter / YAWN_FRAMES) * bar_max_width)
    bar_width_yawn = min(bar_width_yawn, bar_max_width)
    
    cv2.rectangle(frame, (15, bar_y_yawn), (15 + bar_max_width, bar_y_yawn + 25), (80, 80, 80), -1)
    cv2.rectangle(frame, (15, bar_y_yawn), (15 + bar_width_yawn, bar_y_yawn + 25), (0, 165, 255), -1)
    cv2.rectangle(frame, (15, bar_y_yawn), (15 + bar_max_width, bar_y_yawn + 25), (200, 200, 200), 2)
    cv2.putText(frame, f'Menguap: {yawn_counter}/{YAWN_FRAMES}', 
                (15, bar_y_yawn - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

def draw_fps(frame, fps):
    height, width = frame.shape[:2]
    cv2.putText(frame, f'FPS: {int(fps)}', (width - 120, 35), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

def draw_alert(frame, alert_type, current_time):
    height, width = frame.shape[:2]
    
    if int(current_time * 3) % 2 == 0:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (width, 100), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        
        if alert_type == 'eyes':
            text = 'BAHAYA! MATA TERTUTUP TERLALU LAMA!'
            color = (0, 0, 255)
        else:
            text = 'PERINGATAN! TERLALU SERING MENGUAP!'
            color = (0, 165, 255)
        
        cv2.putText(frame, text, (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
        cv2.putText(frame, text, (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def init_model():
    global model
    try:
        model = YOLO(MODEL_PATH)
        print("✅ Model loaded!")
        return True
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return False

def add_incident(status, alert_type):
    with update_lock:
        incident = {
            'date': datetime.now().strftime('%d %b %Y'),
            'time': datetime.now().strftime('%H:%M:%S'),
            'status': status,
            'type': alert_type
        }
        incident_history.insert(0, incident)
        if len(incident_history) > 50:
            incident_history.pop()
        
        status_data['last_incident'] = {
            'status': status,
            'time': datetime.now().strftime('%H:%M:%S')
        }
    
    socketio.emit('new_incident', incident, namespace='/')
    print(f"📊 Incident added: {status} at {incident['time']}")

def play_local_alarm():
    try:
        import winsound
        winsound.Beep(2500, 500)
    except:
        print('\a')

def emit_status_update():
    with update_lock:
        data = status_data.copy()
    socketio.emit('status_update', data, namespace='/')

# ==========================================
# DETECTION FUNCTION
# ==========================================

def generate_frames():
    global detection_active, session_start_time, camera, last_status_emit
    
    camera = cv2.VideoCapture(0)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    camera.set(cv2.CAP_PROP_FPS, 30)
    
    if not camera.isOpened():
        print("❌ Cannot open camera")
        return
    
    if model is None:
        if not init_model():
            return
    
    session_start_time = time.time()
    detection_active = True
    status_data['camera_active'] = True
    
    closed_eye_counter = 0
    yawn_counter = 0
    prev_time = time.time()
    last_alarm_time = 0
    
    print("✅ Detection started!")
    emit_status_update()
    
    while detection_active:
        success, frame = camera.read()
        if not success:
            break
        
        frame = cv2.flip(frame, 1)
        results = model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
        
        closed_eyes_detected = False
        yawning_detected = False
        
        for result in results:
            boxes = result.boxes
            for box in boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                label = CLASS_NAMES[cls]
                color = CLASS_COLORS.get(label, (255, 255, 255))
                
                if label == 'mata_tutup':
                    closed_eyes_detected = True
                elif label == 'nguap':
                    yawning_detected = True
                
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
                label_text = f'{label} {conf:.2f}'
                (text_width, text_height), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.rectangle(frame, (x1, y1 - text_height - 10), (x1 + text_width + 10, y1), color, -1)
                cv2.putText(frame, label_text, (x1 + 5, y1 - 5), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        if closed_eyes_detected:
            closed_eye_counter += 1
        else:
            closed_eye_counter = max(0, closed_eye_counter - 2)
        
        if yawning_detected:
            yawn_counter += 1
        else:
            yawn_counter = max(0, yawn_counter - 1)
        
        curr_time = time.time()
        fps = 1 / (curr_time - prev_time) if curr_time != prev_time else 0
        prev_time = curr_time
        
        session_elapsed = int(time.time() - session_start_time)
        hours = session_elapsed // 3600
        minutes = (session_elapsed % 3600) // 60
        seconds = session_elapsed % 60
        session_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        alert_active = False
        alert_type = None
        current_status = 'NORMAL'
        
        if closed_eye_counter >= CLOSED_EYE_FRAMES:
            alert_active = True
            alert_type = 'eyes'
            current_status = 'MENGANTUK'
        elif yawn_counter >= YAWN_FRAMES:
            alert_active = True
            alert_type = 'yawn'
            current_status = 'MENGANTUK'
        
        if alert_active and (curr_time - last_alarm_time) > ALARM_COOLDOWN:
            play_local_alarm()
            last_alarm_time = curr_time
            print(f"⚠️ ALARM! {alert_type}")
            add_incident(current_status, alert_type)
        
        if alert_active:
            draw_alert(frame, alert_type, curr_time)
        
        draw_progress_bars(frame, closed_eye_counter, yawn_counter)
        draw_fps(frame, fps)
        
        with update_lock:
            status_data.update({
                'closed_eye_counter': closed_eye_counter,
                'yawn_counter': yawn_counter,
                'fps': int(fps),
                'current_status': current_status,
                'session_time': session_time_str,
                'blink_frequency': 15 + (closed_eye_counter % 10),
                'closed_percentage': int((closed_eye_counter / CLOSED_EYE_FRAMES) * 100),
                'yawn_percentage': int((yawn_counter / YAWN_FRAMES) * 100)
            })
        
        if curr_time - last_status_emit > 0.5:
            emit_status_update()
            last_status_emit = curr_time
        
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_bytes = buffer.tobytes()
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    
    if camera:
        camera.release()
    status_data['camera_active'] = False
    print("🛑 Detection stopped")

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    with update_lock:
        return jsonify(status_data)

@app.route('/api/history')
def get_history():
    with update_lock:
        return jsonify(incident_history[:20])

@app.route('/api/reset', methods=['POST'])
def reset_counters():
    global session_start_time
    with update_lock:
        status_data['closed_eye_counter'] = 0
        status_data['yawn_counter'] = 0
        session_start_time = time.time()
    emit_status_update()
    return jsonify({'status': 'success', 'message': 'Counter direset'})

@app.route('/api/stop', methods=['POST'])
def stop_detection():
    global detection_active
    detection_active = False
    return jsonify({'status': 'success', 'message': 'Deteksi dihentikan'})

@app.route('/api/restart', methods=['POST'])
def restart_detection():
    global detection_active
    if not detection_active:
        # Start detection in new thread
        thread = threading.Thread(target=lambda: list(generate_frames()))
        thread.daemon = True
        thread.start()
        return jsonify({'status': 'success', 'message': 'Deteksi dimulai ulang'})
    return jsonify({'status': 'error', 'message': 'Deteksi sudah berjalan'})

# ==========================================
# SOCKETIO EVENTS
# ==========================================

@socketio.on('connect')
def handle_connect():
    print('✅ Client connected')
    with update_lock:
        emit('status_update', status_data)
        emit('history_update', incident_history[:20])

@socketio.on('disconnect')
def handle_disconnect():
    print('❌ Client disconnected')

@socketio.on('request_update')
def handle_request_update():
    emit_status_update()
    with update_lock:
        emit('history_update', incident_history[:20])

# ==========================================
# HTML TEMPLATE
# ==========================================

HTML_TEMPLATE = '''<!DOCTYPE html>
<html class="dark" lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pemantau Kantuk Pengemudi</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" />
    <script>
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    colors: {
                        "primary": "#136dec",
                        "danger": "#ef4444",
                        "success": "#10b981",
                        "background-dark": "#111822", 
                        "surface-dark": "#233348",
                        "surface-dark-lighter": "#324867",
                    }
                }
            }
        }
    </script>
    <style>
        @keyframes slideDown {
            from { transform: translateY(-100%); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        .alert-enter {
            animation: slideDown 0.5s ease-out;
        }
        @keyframes pulse-red {
            0%, 100% { background-color: rgba(239, 68, 68, 0.2); }
            50% { background-color: rgba(239, 68, 68, 0.4); }
        }
        .pulse-red {
            animation: pulse-red 1s ease-in-out infinite;
        }
    </style>
</head>
<body class="bg-background-dark text-white antialiased min-h-screen">
    <!-- Alert Banner -->
    <div id="alert-banner" class="hidden fixed top-0 left-0 right-0 z-50 alert-enter">
        <div class="bg-gradient-to-r from-red-600 via-red-500 to-orange-500 p-4 shadow-2xl">
            <div class="max-w-7xl mx-auto flex items-center justify-between">
                <div class="flex items-center gap-4">
                    <div class="flex items-center justify-center w-12 h-12 rounded-full bg-white/20 pulse-red">
                        <span class="material-symbols-outlined text-3xl text-white">warning</span>
                    </div>
                    <div>
                        <p class="text-white font-bold text-lg" id="alert-title">⚠️ PERINGATAN KANTUK!</p>
                        <p class="text-white/90 text-sm" id="alert-message">Pengemudi terdeteksi mengantuk. Segera istirahat!</p>
                    </div>
                </div>
                <button onclick="closeAlert()" class="text-white hover:bg-white/20 p-2 rounded-lg transition-colors">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>
        </div>
    </div>

    <!-- Header -->
    <header class="sticky top-0 z-40 border-b border-surface-dark-lighter bg-background-dark/95 backdrop-blur">
        <div class="px-4 md:px-10 py-3 flex items-center justify-between">
            <div class="flex items-center gap-4">
                <div class="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/20 text-primary">
                    <span class="material-symbols-outlined text-2xl">visibility</span>
                </div>
                <h1 class="text-lg font-bold">Pemantau Kantuk Pengemudi</h1>
            </div>
            <div class="flex gap-4 items-center">
                <div class="hidden md:flex items-center gap-2">
                    <span class="relative flex h-3 w-3">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-3 w-3 bg-success"></span>
                    </span>
                    <span class="text-sm font-medium text-gray-300">Sistem Online</span>
                </div>
                <div class="flex items-center gap-2 px-4 py-2 rounded-lg bg-surface-dark">
                    <span class="material-symbols-outlined text-[20px]">videocam</span>
                    <span class="text-sm font-bold">Kamera: <span id="camera-status-text">Offline</span></span>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-[1440px] mx-auto px-4 md:px-10 lg:px-40 py-8">
        <!-- Video Section -->
        <div class="mb-10">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Umpan Kamera Langsung</h2>
                <div class="flex gap-2">
                    <button onclick="resetCounters()" class="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary hover:bg-primary/80 transition-colors">
                        <span class="material-symbols-outlined text-[20px]">refresh</span>
                        <span class="font-medium">Reset</span>
                    </button>
                    <button onclick="stopDetection()" class="flex items-center gap-2 px-4 py-2 rounded-lg bg-danger hover:bg-danger/80 transition-colors">
                        <span class="material-symbols-outlined text-[20px]">stop</span>
                        <span class="font-medium">Stop</span>
                    </button>
                </div>
            </div>
            
            <div class="relative aspect-video rounded-xl overflow-hidden bg-black border border-surface-dark-lighter shadow-2xl">
                <img src="/video_feed" class="w-full h-full object-cover" alt="Video Feed">
            </div>

            <div class="mt-4 bg-surface-dark/50 border border-surface-dark-lighter rounded-lg p-3">
                <p class="text-sm text-gray-400 font-mono text-center">R=Reset | S=Stop | ESC=Keluar</p>
            </div>
        </div>

        <!-- Status Cards -->
        <div class="mb-10">
            <h2 class="text-2xl font-bold mb-4">Status Pengemudi</h2>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Status Saat Ini -->
                <div id="status-card" class="rounded-xl p-6 bg-surface-dark border-l-4 border-success relative overflow-hidden shadow-lg transition-all duration-300">
                    <div class="absolute right-0 top-0 p-4 opacity-10">
                        <span class="material-symbols-outlined text-[140px]">check_circle</span>
                    </div>
                    <div class="relative z-10">
                        <div class="flex items-center gap-3 mb-4">
                            <div class="p-2 bg-success/20 rounded-full">
                                <span class="material-symbols-outlined text-success">health_and_safety</span>
                            </div>
                            <p class="text-gray-400 text-sm font-medium uppercase tracking-wider">Status Saat Ini</p>
                        </div>
                        <p id="status-text" class="text-5xl font-bold mb-2">NORMAL</p>
                        <p id="status-subtitle" class="text-success text-lg font-medium flex items-center gap-1">
                            <span class="material-symbols-outlined text-xl">trending_up</span>
                            Waspada & Fokus
                        </p>
                        <div class="mt-6 pt-6 border-t border-surface-dark-lighter flex justify-between">
                            <div>
                                <p class="text-gray-400 text-xs">Sesi</p>
                                <p id="session-time" class="text-white font-mono text-lg">00:00:00</p>
                            </div>
                            <div>
                                <p class="text-gray-400 text-xs text-right">Frekuensi Kedipan</p>
                                <p class="text-white font-mono text-lg text-right"><span id="blink-freq">18</span> / mnt</p>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Insiden Terakhir -->
                <div id="incident-card" class="rounded-xl p-6 bg-surface-dark border-l-4 border-gray-600 shadow-lg">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="p-2 bg-danger/20 rounded-full">
                            <span class="material-symbols-outlined text-danger">notifications_active</span>
                        </div>
                        <p class="text-gray-400 text-sm font-medium uppercase tracking-wider">Insiden Terakhir</p>
                    </div>
                    <p id="last-incident-status" class="text-2xl font-bold mb-1 text-gray-400">Belum Ada</p>
                    <p id="last-incident-time" class="text-gray-400 text-sm">-</p>
                </div>
            </div>
        </div>

        <!-- Riwayat Insiden -->
        <div>
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-2xl font-bold">Riwayat Insiden (<span id="incident-count">0</span>)</h2>
                <div class="flex gap-2">
                    <button class="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-dark text-gray-300 hover:bg-surface-dark-lighter transition-colors">
                        <span class="material-symbols-outlined text-[18px]">filter_list</span>
                        <span class="text-sm">Filter</span>
                    </button>
                    <button class="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/20 text-primary hover:bg-primary/30 transition-colors">
                        <span class="material-symbols-outlined text-[18px]">download</span>
                        <span class="text-sm font-medium">Ekspor</span>
                    </button>
                </div>
            </div>

            <div class="rounded-xl border border-surface-dark-lighter bg-surface-dark shadow-xl overflow-hidden">
                <table class="w-full">
                    <thead>
                        <tr class="bg-surface-dark-lighter border-b border-surface-dark-lighter">
                            <th class="px-6 py-4 text-left text-gray-400 text-xs font-semibold uppercase">Tanggal</th>
                            <th class="px-6 py-4 text-left text-gray-400 text-xs font-semibold uppercase">Waktu</th>
                            <th class="px-6 py-4 text-left text-gray-400 text-xs font-semibold uppercase">Status</th>
                        </tr>
                    </thead>
                    <tbody id="history-body" class="divide-y divide-surface-dark-lighter">
                        <tr>
                            <td colspan="3" class="px-6 py-8 text-center text-gray-400">Belum ada insiden tercatat</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <script>
        const socket = io();
        let alertTimeout;
        
        socket.on('connect', () => {
            console.log('✅ Connected');
            socket.emit('request_update');
        });
        
        socket.on('status_update', (data) => {
            console.log('📊 Status:', data);
            
            // Update camera status
            const cameraText = document.getElementById('camera-status-text');
            cameraText.textContent = data.camera_active ? 'Aktif' : 'Offline';
            cameraText.className = data.camera_active ? 'text-success' : 'text-gray-400';
            
            // Update status card
            const statusCard = document.getElementById('status-card');
            const statusText = document.getElementById('status-text');
            const statusSubtitle = document.getElementById('status-subtitle');
            
            statusText.textContent = data.current_status;
            
            if (data.current_status === 'MENGANTUK') {
                statusCard.className = 'rounded-xl p-6 bg-surface-dark border-l-4 border-danger relative overflow-hidden shadow-lg transition-all duration-300 pulse-red';
                statusText.className = 'text-5xl font-bold mb-2 text-danger';
                statusSubtitle.innerHTML = '<span class="material-symbols-outlined text-xl">warning</span> Terdeteksi Kantuk!';
                statusSubtitle.className = 'text-danger text-lg font-medium flex items-center gap-1';
                
                // Show alert banner
                showAlert(data.current_status);
            } else {
                statusCard.className = 'rounded-xl p-6 bg-surface-dark border-l-4 border-success relative overflow-hidden shadow-lg transition-all duration-300';
                statusText.className = 'text-5xl font-bold mb-2 text-white';
                statusSubtitle.innerHTML = '<span class="material-symbols-outlined text-xl">trending_up</span> Waspada & Fokus';
                statusSubtitle.className = 'text-success text-lg font-medium flex items-center gap-1';
            }
            
            // Update session info
            document.getElementById('session-time').textContent = data.session_time || '00:00:00';
            document.getElementById('blink-freq').textContent = data.blink_frequency || 18;
            
            // Update last incident
            if (data.last_incident && data.last_incident.status !== 'Belum Ada') {
                const incidentCard = document.getElementById('incident-card');
                const lastStatus = document.getElementById('last-incident-status');
                const lastTime = document.getElementById('last-incident-time');
                
                lastStatus.textContent = data.last_incident.status;
                lastTime.textContent = data.last_incident.time;
                
                incidentCard.className = 'rounded-xl p-6 bg-surface-dark border-l-4 border-danger shadow-lg';
                lastStatus.className = 'text-2xl font-bold mb-1 text-danger';
            }
        });
        
        socket.on('new_incident', (incident) => {
            console.log('🚨 New incident:', incident);
            updateHistory();
        });
        
        socket.on('history_update', (history) => {
            renderHistory(history);
        });
        
        function showAlert(status) {
            const banner = document.getElementById('alert-banner');
            const title = document.getElementById('alert-title');
            const message = document.getElementById('alert-message');
            
            if (status === 'MENGANTUK') {
                title.textContent = '⚠️ PERINGATAN KANTUK TERDETEKSI!';
                message.textContent = 'Pengemudi menunjukkan tanda-tanda kantuk. Segera istirahat atau berhenti di tempat aman!';
                
                banner.classList.remove('hidden');
                
                // Auto close after 10 seconds
                clearTimeout(alertTimeout);
                alertTimeout = setTimeout(() => {
                    banner.classList.add('hidden');
                }, 10000);
            }
        }
        
        function closeAlert() {
            document.getElementById('alert-banner').classList.add('hidden');
            clearTimeout(alertTimeout);
        }
        
        function renderHistory(history) {
            const tbody = document.getElementById('history-body');
            const countElem = document.getElementById('incident-count');
            
            countElem.textContent = history ? history.length : 0;
            
            if (!history || history.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" class="px-6 py-8 text-center text-gray-400">Belum ada insiden tercatat</td></tr>';
                return;
            }
            
            tbody.innerHTML = history.map(i => `
                <tr class="hover:bg-surface-dark-lighter transition-colors">
                    <td class="px-6 py-4 text-gray-400 text-sm">${i.date}</td>
                    <td class="px-6 py-4 text-white text-sm font-mono">${i.time}</td>
                    <td class="px-6 py-4">
                        <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-danger/10 text-danger text-sm font-bold border border-danger/20">
                            <span class="w-2 h-2 rounded-full bg-danger"></span>
                            ${i.status}
                        </span>
                    </td>
                </tr>
            `).join('');
        }
        
        function updateHistory() {
            fetch('/api/history')
                .then(r => r.json())
                .then(renderHistory)
                .catch(e => console.error(e));
        }
        
        function resetCounters() {
            if (confirm('🔄 Reset semua counter dan mulai sesi baru?')) {
                fetch('/api/reset', {method: 'POST'})
                    .then(r => r.json())
                    .then(data => {
                        showNotification('✅ ' + data.message, 'success');
                        socket.emit('request_update');
                    })
                    .catch(e => {
                        console.error(e);
                        showNotification('❌ Gagal reset counter', 'error');
                    });
            }
        }
        
        function stopDetection() {
            if (confirm('⏹️ Hentikan deteksi kantuk?')) {
                fetch('/api/stop', {method: 'POST'})
                    .then(r => r.json())
                    .then(data => {
                        showNotification('⏹️ ' + data.message, 'success');
                        setTimeout(() => {
                            if (confirm('🔄 Mulai deteksi ulang?')) {
                                restartDetection();
                            }
                        }, 1000);
                    })
                    .catch(e => {
                        console.error(e);
                        showNotification('❌ Gagal menghentikan deteksi', 'error');
                    });
            }
        }
        
        function restartDetection() {
            fetch('/api/restart', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'success') {
                        showNotification('✅ ' + data.message, 'success');
                        setTimeout(() => location.reload(), 1500);
                    } else {
                        showNotification('⚠️ ' + data.message, 'warning');
                    }
                })
                .catch(e => {
                    console.error(e);
                    showNotification('❌ Gagal memulai ulang deteksi', 'error');
                });
        }
        
        function showNotification(message, type = 'info') {
            const colors = {
                success: 'bg-success',
                error: 'bg-danger',
                warning: 'bg-orange-500',
                info: 'bg-primary'
            };
            
            const notification = document.createElement('div');
            notification.className = `fixed top-20 right-4 ${colors[type]} text-white px-6 py-3 rounded-lg shadow-xl z-50 animate-pulse`;
            notification.textContent = message;
            
            document.body.appendChild(notification);
            
            setTimeout(() => {
                notification.style.opacity = '0';
                notification.style.transition = 'opacity 0.3s';
                setTimeout(() => notification.remove(), 300);
            }, 3000);
        }
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'r' || e.key === 'R') {
                resetCounters();
            } else if (e.key === 's' || e.key === 'S') {
                stopDetection();
            } else if (e.key === 'Escape') {
                if (confirm('Tutup aplikasi?')) {
                    window.close();
                }
            }
        });
        
        // Initial load
        updateHistory();
        setInterval(updateHistory, 5000);
    </script>
</body>
</html>'''

# ==========================================
# MAIN
# ==========================================

if __name__ == '__main__':
    print("="*60)
    print("DROWSINESS DETECTION WEB APP - MODERN UI")
    print("="*60)
    print("\n📦 Loading model...")
    
    if init_model():
        print("\n✅ Server starting...")
        print("🌐 Open: http://localhost:5000")
        print("🛑 Ctrl+C to stop\n")
        print("="*60)
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    else:
        print("\n❌ Failed to load model")
        print("💡 Make sure 'best (1).pt' is in the same folder")