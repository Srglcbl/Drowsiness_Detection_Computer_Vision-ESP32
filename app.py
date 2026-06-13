"""
===============================================
DROWSINESS DETECTION FLASK WEB APP
Jalankan: python app.py
Akses: http://localhost:5000
===============================================
"""

from flask import Flask, render_template, Response, jsonify, request
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
# Konfigurasi WAKTU (Detik/Seconds)
CLOSED_EYE_THRESHOLD = 2.0   
YAWN_THRESHOLD = 2.0        
ALARM_COOLDOWN = 3
CONFIDENCE_THRESHOLD = 0.45

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
    'max_closed': CLOSED_EYE_THRESHOLD,
    'max_yawn': YAWN_THRESHOLD,
    'fps': 0,
    'current_status': 'NORMAL',
    'session_time': '00:00:00',
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

import sqlite3
import os
import signal


# ==========================================
# DATABASE FUNCTIONS
# ==========================================

def init_db():
    conn = sqlite3.connect('drowsiness.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            status TEXT,
            alert_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("📂 Database initialized (drowsiness.db)")

def add_incident(status, alert_type):
    with update_lock:
        incident = {
            'date': datetime.now().strftime('%d %b %Y'),
            'time': datetime.now().strftime('%H:%M:%S'),
            'status': status,
            'type': alert_type
        }
        
        # Save to DB
        try:
            conn = sqlite3.connect('drowsiness.db')
            c = conn.cursor()
            c.execute("INSERT INTO incidents (date, time, status, alert_type) VALUES (?, ?, ?, ?)",
                      (incident['date'], incident['time'], status, alert_type))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ DB Error: {e}")
            
        # Update memory list for fast access (optional, but good for real-time)
        incident_history.insert(0, incident)
        if len(incident_history) > 50:
            incident_history.pop()
        
        status_data['last_incident'] = {
            'status': status,
            'time': datetime.now().strftime('%H:%M:%S')
        }
    
    socketio.emit('new_incident', incident, namespace='/')
    # Fetch updated history from DB to be sure
    with sqlite3.connect('drowsiness.db') as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        history_list = [dict(row) for row in rows]
        
    socketio.emit('history_update', history_list, namespace='/')
    print(f"📊 Incident added: {status} at {incident['time']}")

def play_local_alarm():
    # ==============================================================================
    # ⚠️ KONFIGURASI ALARM MP3
    # ==============================================================================
    alarm_filename = 'alarm.mp3'
    
    def run_sound():
        try:
            # Menggunakan library pygame yang lebih stabil untuk MP3 di Windows
            import pygame
            import os
            
            # Mendapatkan full path ke file mp3
            current_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(current_dir, alarm_filename)
            
            if os.path.exists(file_path):
                # Init mixer jika belum
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                
                # Load dan mainkan
                pygame.mixer.music.load(file_path)
                pygame.mixer.music.play()
                
                # Tunggu sampai selesai (penting karena dalam thread)
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
            else:
                print(f"⚠️ File '{alarm_filename}' tidak ditemukan di {current_dir}")
                # Fallback ke beep jika file tidak ada
                import winsound
                winsound.Beep(2500, 800)
                
        except ImportError:
            print("⚠️ Modul 'pygame' belum terinstall. Jalankan: pip install pygame")
            # Fallback ke beep standar
            try:
                import winsound
                winsound.Beep(2500, 800)
            except:
                pass
        except Exception as e:
            print(f"❌ Error memutar audio: {e}")
            # Fallback
            try:
                import winsound
                winsound.Beep(2500, 800)
            except:
                pass

    # Jalankan di thread thread terpisah agar video stream tidak macet/freeze saat alarm bunyi
    threading.Thread(target=run_sound, daemon=True).start()

def emit_status_update():
    with update_lock:
        data = status_data.copy()
    socketio.emit('status_update', data, namespace='/')

# ==========================================
# DETECTION FUNCTION
# ==========================================

def generate_frames():
    global detection_active, session_start_time, camera, last_status_emit
    
    camera = cv2.VideoCapture(1)
    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
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
    
    # Counter sekarang dalam satuan DETIK (float)
    closed_eye_timer = 0.0
    yawn_timer = 0.0
    
    prev_time = time.time()
    last_alarm_time = 0
    
    print("✅ Detection started!")
    emit_status_update()
    
    while detection_active:
        curr_time = time.time()
        delta_time = curr_time - prev_time
        prev_time = curr_time
        fps = 1 / delta_time if delta_time > 0 else 0
        
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
        
        # LOGIKA PERHITUNGAN WAKTU (Seconds Based)
        if closed_eyes_detected:
            closed_eye_timer += delta_time
        else:
            # Turun perlahan (decay)
            closed_eye_timer = max(0.0, closed_eye_timer - (delta_time * 2))
        
        if yawning_detected:
            yawn_timer += delta_time
        else:
            yawn_timer = max(0.0, yawn_timer - (delta_time * 2))
        
        session_elapsed = int(time.time() - session_start_time)
        hours = session_elapsed // 3600
        minutes = (session_elapsed % 3600) // 60
        seconds = session_elapsed % 60
        session_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        alert_active = False
        alert_type = None
        current_status = 'NORMAL'
        
        # Cek Threshold Waktu
        if closed_eye_timer >= CLOSED_EYE_THRESHOLD:
            alert_active = True
            alert_type = 'eyes'
            current_status = 'MENGANTUK'
        elif yawn_timer >= YAWN_THRESHOLD:
            alert_active = True
            alert_type = 'yawn'
            current_status = 'MENGANTUK'
        
        if alert_active and (curr_time - last_alarm_time) > ALARM_COOLDOWN:
            play_local_alarm()
            last_alarm_time = curr_time
            print(f"⚠️ ALARM! {alert_type}")
            add_incident(current_status, alert_type)
            
            # --- ESP32 TRIGGER ---
            try:
                ESP_IP = "10.254.31.113" 
                import requests
                try:
                    requests.get(f"http://{ESP_IP}/alert?type={alert_type}", timeout=0.5)
                except:
                    pass
            except Exception as e:
                print(f"ESP Error: {e}")
            # ---------------------
        
        with update_lock:
            status_data.update({
                'closed_eye_counter': round(closed_eye_timer, 1), # Kirim float 1 desimal
                'yawn_counter': round(yawn_timer, 1),
                'fps': int(fps),
                'current_status': current_status,
                'session_time': session_time_str
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
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    with update_lock:
        return jsonify(status_data)

@app.route('/api/stop_alarm')
def stop_alarm():
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            print("🔊 Alarm stopped via remote request (ESP32)")
        return jsonify({'status': 'stopped'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/history')
def get_history():
    try:
        conn = sqlite3.connect('drowsiness.db')
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        print(f"DB Error: {e}")
        return jsonify([])

@app.route('/api/export')
def export_data():
    try:
        import pandas as pd
        conn = sqlite3.connect('drowsiness.db')
        df = pd.read_sql_query("SELECT * FROM incidents ORDER BY id DESC", conn)
        conn.close()
        
        # Create Excel file in memory
        from io import BytesIO
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Riwayat Insiden')
        output.seek(0)
        
        return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                       headers={"Content-Disposition": "attachment;filename=riwayat_kantuk.xlsx"})
    except ImportError:
        return jsonify({"error": "Modul pandas/openpyxl belum terinstall. Jalankan: pip install pandas openpyxl"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop', methods=['POST'])
def stop_system():
    global detection_active
    detection_active = False
    
    def shutdown_server():
        time.sleep(1) # Give time to return response
        print("🛑 Shutting down system...")
        os.kill(os.getpid(), signal.SIGINT)
        
    threading.Thread(target=shutdown_server).start()
    return jsonify({'status': 'shutting_down'})

@app.route('/api/reset', methods=['POST'])
def reset_counters():
    global session_start_time
    # Hanya me-reset sesi/timer, tidak menghapus data histori
    session_start_time = time.time()
    return jsonify({'status': 'reset'})

@app.route('/api/clear_history', methods=['POST'])
def clear_history():
    try:
        conn = sqlite3.connect('drowsiness.db')
        c = conn.cursor()
        c.execute("DELETE FROM incidents") # Hapus semua data
        # Reset Auto Increment (opsional, agar id mulai dari 1 lagi)
        c.execute("DELETE FROM sqlite_sequence WHERE name='incidents'")
        conn.commit()
        conn.close()
        
        # Bersihkan memory list juga
        incident_history.clear()
        socketio.emit('history_update', [])
        
        return jsonify({'status': 'cleared'})
    except Exception as e:
        print(f"DB Error: {e}")
        return jsonify({'error': str(e)}), 500

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
# MAIN
# ==========================================

if __name__ == '__main__':
    print("="*60)
    print("DROWSINESS DETECTION WEB APP")
    print("="*60)
    print("\n📦 Loading model...")
    
    if init_model():
        init_db()
        print("\n✅ Server starting...")
        print("🌐 Open: http://localhost:5000")
        print("🛑 Ctrl+C to stop\n")
        print("="*60)
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
    else:
        print("\n❌ Failed to load model")