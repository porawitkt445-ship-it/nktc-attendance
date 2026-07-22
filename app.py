from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
import sqlite3, cv2, os, numpy as np, base64, pickle, time
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# ดึงไฟล์ Blueprint เข้ามาลิงก์กัน
from departments import departments_bp, get_class_list
from teachers import teachers_bp, init_teachers_db

app = Flask(__name__)
app.secret_key = 'super_secret_key' 

# เปิดใช้งานระบบแอปย่อย (Blueprints)
app.register_blueprint(departments_bp)
app.register_blueprint(teachers_bp)

UPLOAD_FOLDER = 'img'
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

# ตัวแปรระดับ Global สำหรับจัดการการสลับกล้องอัตโนมัติ
LAST_MOBILE_SEEN = 0.0
MOBILE_TIMEOUT = 4.0

# ฟังก์ชันจัดการฐานข้อมูลหลัก
def init_db():
    conn = sqlite3.connect("attendance.db")
    
    conn.execute('''CREATE TABLE IF NOT EXISTS students (
        student_id TEXT PRIMARY KEY, 
        name TEXT, 
        department TEXT, 
        room TEXT, 
        class_group TEXT, 
        pdpa_consent INTEGER
    )''')
    
    try: conn.execute("ALTER TABLE students ADD COLUMN citizen_id TEXT")
    except: pass
    try: conn.execute("ALTER TABLE students ADD COLUMN phone TEXT")
    except: pass
    try: conn.execute("ALTER TABLE students ADD COLUMN address TEXT")
    except: pass
    try: conn.execute("ALTER TABLE students ADD COLUMN status TEXT")
    except: pass
    
    conn.execute('''CREATE TABLE IF NOT EXISTS attendance_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # ✅ เพิ่มคอลัมน์ status ในตาราง attendance_logs รองรับสถานะต่างๆ
    try: conn.execute("ALTER TABLE attendance_logs ADD COLUMN status TEXT DEFAULT 'มาเรียน'")
    except: pass
    
    conn.commit()
    conn.close()
    
    # เรียกใช้งานสร้างตารางครูจากไฟล์ teachers.py
    init_teachers_db()

init_db()

def connect_db(): return sqlite3.connect("attendance.db")

# ระบบ AI
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
recognizer = cv2.face.LBPHFaceRecognizer_create()
is_ai_ready = False
labels = {}

def load_ai_model():
    global is_ai_ready, labels
    if os.path.exists("trainer.yml") and os.path.exists("labels.pkl"):
        recognizer.read("trainer.yml")
        with open("labels.pkl", "rb") as f: labels = pickle.load(f)
        is_ai_ready = True
load_ai_model()

def train_ai_auto():
    label_ids, y_labels, x_train, current_id = {}, [], [], 0
    for file in os.listdir(UPLOAD_FOLDER):
        if file.lower().endswith((".jpg", ".png")):
            student_id = os.path.splitext(file)[0]
            if student_id not in label_ids.values(): 
                label_ids[current_id] = student_id
                current_id += 1
            id_ = [k for k, v in label_ids.items() if v == student_id][0]
            img = Image.open(os.path.join(UPLOAD_FOLDER, file)).convert("L")
            faces = face_cascade.detectMultiScale(np.array(img, "uint8"), 1.1, 4)
            for (x, y, w, h) in faces: 
                x_train.append(np.array(img, "uint8")[y:y+h, x:x+w])
                y_labels.append(id_)
    if x_train:
        recognizer.train(x_train, np.array(y_labels))
        recognizer.save("trainer.yml")
        with open("labels.pkl", "wb") as f: pickle.dump(label_ids, f)

# ระบบป้องกันการสแกนซ้ำ
scanned_students = {}
SCAN_COOLDOWN = 300 

def log_attendance(student_id):
    current_time = time.time()
    if student_id in scanned_students:
        if current_time - scanned_students[student_id] < SCAN_COOLDOWN:
            return 
            
    try:
        conn = connect_db()
        cur = conn.execute("SELECT COUNT(*) FROM attendance_logs WHERE student_id = ? AND date(timestamp) = date('now', 'localtime')", (student_id,))
        if cur.fetchone()[0] == 0:
            conn.execute("INSERT INTO attendance_logs (student_id, status) VALUES (?, 'มาเรียน')", (student_id,))
            conn.commit()
            scanned_students[student_id] = current_time
        conn.close()
    except sqlite3.Error as e:
        print(f"Database error: {e}")

# ระบบประมวลผลกล้อง
def generate_frames():
    global LAST_MOBILE_SEEN
    camera = None
    try:
        while True:
            is_mobile_active = (time.time() - LAST_MOBILE_SEEN) < MOBILE_TIMEOUT
            if is_mobile_active:
                if camera is not None and camera.isOpened():
                    camera.release()
                    camera = None
                blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank_frame, "KT Network Mobile Active...", (90, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 165, 255), 2)
                _, buffer = cv2.imencode('.jpg', blank_frame)
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(0.5)
                continue
            if camera is None or not camera.isOpened():
                camera = cv2.VideoCapture(0)
            success, frame = camera.read()
            if not success: continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.2, 5)
            for (x, y, w, h) in faces:
                student_id = "Unknown"
                if is_ai_ready:
                    id_, conf = recognizer.predict(gray[y:y+h, x:x+w])
                    if conf < 100: student_id = labels.get(id_, "Unknown")
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(frame, student_id, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                if student_id != "Unknown": log_attendance(student_id)
            _, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
    finally: 
        if camera is not None and camera.isOpened(): camera.release()

@app.route('/api/process-frame', methods=['POST'])
def process_frame():
    global LAST_MOBILE_SEEN
    try:
        LAST_MOBILE_SEEN = time.time()
        data = request.json
        header, encoded = data['image'].split(",", 1)
        nparr = np.frombuffer(base64.b64decode(encoded), np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.2, 5)
        student_id = "Unknown"
        if is_ai_ready and len(faces) > 0:
            for (x, y, w, h) in faces:
                id_, conf = recognizer.predict(gray[y:y+h, x:x+w])
                if conf < 100: 
                    student_id = labels.get(id_, "Unknown")
                    if student_id != "Unknown":
                        log_attendance(student_id)
                        break
        return jsonify({"student_id": student_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/')
def home(): return redirect(url_for('teachers.login_page'))

@app.route('/dashboard')
def index(): 
    if 'username' not in session: return redirect(url_for('teachers.login_page'))
    
    conn = connect_db()
    cur = conn.execute("SELECT profile_img FROM teachers WHERE username = ?", (session['username'],))
    teacher_data = cur.fetchone()
    conn.close()
    
    profile_img = teacher_data[0] if teacher_data and teacher_data[0] else ""

    return render_template('index.html', 
                           department=session.get('department'),
                           teacher_name=session.get('teacher_name'),
                           teacher_room=session.get('teacher_room'),
                           profile_img=profile_img)

@app.route('/register')
def register_page(): 
    if 'username' not in session: return redirect(url_for('teachers.login_page'))
    
    conn = connect_db()
    cur = conn.execute("SELECT profile_img FROM teachers WHERE username = ?", (session['username'],))
    teacher_data = cur.fetchone()
    conn.close()
    
    profile_img = teacher_data[0] if teacher_data and teacher_data[0] else ""
    
    dept = session.get('department', '')
    class_list = get_class_list(dept)
    
    return render_template('register.html', 
                           department=dept, 
                           teacher_room=session.get('teacher_room'), 
                           teacher_name=session.get('teacher_name'),
                           profile_img=profile_img,
                           class_list=class_list)

@app.route('/report')
def report_page(): 
    if 'username' not in session: return redirect(url_for('teachers.login_page'))
    
    conn = connect_db()
    cur = conn.execute("SELECT profile_img FROM teachers WHERE username = ?", (session['username'],))
    teacher_data = cur.fetchone()
    conn.close()
    
    profile_img = teacher_data[0] if teacher_data and teacher_data[0] else ""
    
    return render_template('report.html', 
                           teacher_name=session.get('teacher_name'),
                           profile_img=profile_img,
                           department=session.get('department'))

@app.route('/scan')
def scan_page(): return render_template('scan.html')
@app.route('/scan_mobile')
def scan_mobile_page(): return render_template('scan_mobile.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    
    citizen_id = data.get('citizen_id', '')
    phone = data.get('phone', '')
    address = data.get('address', '')
    status = data.get('status', 'กำลังศึกษา')
    department = data.get('department', '')
    room = data.get('room', '')
    class_group = data.get('class_group', '')
    
    conn = connect_db()
    try:
        conn.execute("""
            REPLACE INTO students (student_id, name, department, room, class_group, citizen_id, phone, address, status, pdpa_consent) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (data['student_id'], data['name'], department, room, class_group, citizen_id, phone, address, status))
    except sqlite3.OperationalError:
        conn.execute("REPLACE INTO students (student_id, name, department, room, class_group, pdpa_consent) VALUES (?, ?, ?, ?, ?, 1)", 
                     (data['student_id'], data['name'], department, room, class_group))
        
    conn.commit()
    conn.close()
    
    if 'image' in data and data['image']:
        with open(f"img/{data['student_id']}.jpg", "wb") as f: 
            f.write(base64.b64decode(data['image'].split(",")[1]))
        train_ai_auto()
        load_ai_model()
        
    return jsonify({"status": "success"})

# ✅ API สำหรับบันทึกเช็คชื่อย้อนหลัง (แก้ไขเรื่องเวลาคลาดเคลื่อน 7 ชม.)
@app.route('/api/manual-checkin', methods=['POST'])
def manual_checkin():
    if 'username' not in session: return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    student_id = data.get('student_id')
    check_date = data.get('date')
    check_time = data.get('time', '08:30')
    status = data.get('status', 'มาเรียน')
    
    if not student_id or not check_date:
        return jsonify({"status": "error", "message": "ข้อมูลไม่ครบถ้วน"})
        
    conn = connect_db()
    try:
        # แปลงเวลาท้องถิ่นเป็น UTC โดยหักออก 7 ชั่วโมง เพื่อให้เวลาตรงกันเมื่อแสดงผลด้วย localtime
        dt_local = datetime.strptime(f"{check_date} {check_time}:00", "%Y-%m-%d %H:%M:%S")
        dt_utc = dt_local - timedelta(hours=7)
        full_timestamp = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
        
        cur = conn.execute("SELECT id FROM attendance_logs WHERE student_id = ? AND date(timestamp, 'localtime') = ?", (student_id, check_date))
        row = cur.fetchone()
        
        if status == 'ขาด' or status == 'ไม่เข้าร่วม':
            if row:
                conn.execute("DELETE FROM attendance_logs WHERE id = ?", (row[0],))
        else:
            if row:
                conn.execute("UPDATE attendance_logs SET status = ?, timestamp = ? WHERE id = ?", (status, full_timestamp, row[0]))
            else:
                conn.execute("INSERT INTO attendance_logs (student_id, timestamp, status) VALUES (?, ?, ?)", (student_id, full_timestamp, status))
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/attendance-logs')
def get_logs():
    dept = session.get('department', '')
    selected_date = request.args.get('date')
    conn = connect_db()
    
    date_condition = f"date(l.timestamp, 'localtime') = '{selected_date}'" if selected_date else "date(l.timestamp, 'localtime') = date('now', 'localtime')"
    
    if dept == 'ทุกแผนก':
        query = f"""SELECT l.id, l.student_id, s.name, s.department, s.class_group, strftime('%d/%m/%Y %H:%M', l.timestamp, 'localtime'), l.status 
                   FROM attendance_logs l JOIN students s ON l.student_id = s.student_id 
                   WHERE {date_condition} ORDER BY l.timestamp DESC"""
        params = ()
    else:
        query = f"""SELECT l.id, l.student_id, s.name, s.department, s.class_group, strftime('%d/%m/%Y %H:%M', l.timestamp, 'localtime'), l.status 
                   FROM attendance_logs l JOIN students s ON l.student_id = s.student_id 
                   WHERE s.department = ? AND {date_condition} ORDER BY l.timestamp DESC"""
        params = (dept,)
        
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([{
        "id": r[0], 
        "student_id": r[1], 
        "name": r[2], 
        "department": r[3], 
        "class_group": r[4], 
        "timestamp": r[5],
        "status": r[6] if r[6] else 'มาเรียน'
    } for r in rows])

@app.route('/api/absent-students')
def get_absent_students():
    dept = session.get('department', '')
    selected_date = request.args.get('date')
    conn = connect_db()
    
    date_condition = f"date(timestamp, 'localtime') = '{selected_date}'" if selected_date else "date(timestamp, 'localtime') = date('now', 'localtime')"
    
    if dept == 'ทุกแผนก':
        query = f"""SELECT student_id, name, department, class_group FROM students 
                   WHERE student_id NOT IN (SELECT student_id FROM attendance_logs WHERE {date_condition})"""
        params = ()
    else:
        query = f"""SELECT student_id, name, department, class_group FROM students 
                   WHERE department = ? AND student_id NOT IN (SELECT student_id FROM attendance_logs WHERE {date_condition})"""
        params = (dept,)
        
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([{"id": None, "student_id": r[0], "name": r[1], "department": r[2], "class_group": r[3]} for r in rows])

@app.route('/video_feed')
def video_feed(): return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/delete-student/<student_id>', methods=['DELETE'])
def delete_student(student_id):
    try:
        conn = sqlite3.connect("attendance.db")
        conn.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
        conn.execute("DELETE FROM attendance_logs WHERE student_id = ?", (student_id,))
        conn.commit(); conn.close()
        img_path = os.path.join(UPLOAD_FOLDER, f"{student_id}.jpg")
        if os.path.exists(img_path): os.remove(img_path)
        if student_id in scanned_students: del scanned_students[student_id]
        train_ai_auto(); load_ai_model()
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"}), 500
    
@app.route('/api/delete-log/<int:log_id>', methods=['DELETE'])
def delete_log(log_id):
    try:
        conn = connect_db()
        conn.execute("DELETE FROM attendance_logs WHERE id = ?", (log_id,))
        conn.commit(); conn.close()
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"}), 500

@app.route('/students')
def students_page():
    if 'username' not in session: return redirect(url_for('teachers.login_page'))
    
    conn = connect_db()
    cur = conn.execute("SELECT profile_img FROM teachers WHERE username = ?", (session['username'],))
    teacher_data = cur.fetchone()
    conn.close()
    
    profile_img = teacher_data[0] if teacher_data and teacher_data[0] else ""
    
    dept = session.get('department', '')
    class_list = get_class_list(dept)
    
    return render_template('students.html', 
                           teacher_name=session.get('teacher_name'),
                           profile_img=profile_img,
                           department=dept,
                           class_list=class_list)

@app.route('/api/students')
def get_students():
    dept = session.get('department', '')
    conn = connect_db()
    
    try:
        if dept == 'ทุกแผนก':
            rows = conn.execute("SELECT student_id, name, department, class_group, phone, address, status FROM students ORDER BY class_group, student_id").fetchall()
        else:
            rows = conn.execute("SELECT student_id, name, department, class_group, phone, address, status FROM students WHERE department = ? ORDER BY class_group, student_id", (dept,)).fetchall()
        result = [{"student_id": r[0], "name": r[1], "department": r[2], "class_group": r[3], "phone": r[4], "address": r[5], "status": r[6]} for r in rows]
        
    except sqlite3.OperationalError:
        if dept == 'ทุกแผนก':
            rows = conn.execute("SELECT student_id, name, department, class_group FROM students ORDER BY class_group, student_id").fetchall()
        else:
            rows = conn.execute("SELECT student_id, name, department, class_group FROM students WHERE department = ? ORDER BY class_group, student_id", (dept,)).fetchall()
        result = [{"student_id": r[0], "name": r[1], "department": r[2], "class_group": r[3], "phone": "-", "address": "-", "status": "-"} for r in rows]
        
    conn.close()
    return jsonify(result)

@app.route('/api/edit-student', methods=['POST'])
def edit_student():
    data = request.json
    try:
        conn = connect_db()
        try:
            conn.execute("""
                UPDATE students 
                SET name=?, class_group=?, phone=?, address=?, status=? 
                WHERE student_id=?
            """, (data['name'], data['class_group'], data.get('phone', ''), data.get('address', ''), data.get('status', 'กำลังศึกษา'), data['student_id']))
        except sqlite3.OperationalError:
            conn.execute("""
                UPDATE students 
                SET name=?, class_group=? 
                WHERE student_id=?
            """, (data['name'], data['class_group'], data['student_id']))
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/dashboard-stats')
def dashboard_stats():
    if 'username' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    dept = session.get('department', '')
    conn = connect_db()
    
    try:
        if dept == 'ทุกแผนก':
            total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            
            present = conn.execute("""
                SELECT COUNT(*) FROM attendance_logs l 
                JOIN students s ON l.student_id = s.student_id 
                WHERE date(l.timestamp, 'localtime') = date('now', 'localtime') AND (l.status = 'มาเรียน' OR l.status IS NULL OR l.status = '')
            """).fetchone()[0]
            
            late = conn.execute("""
                SELECT COUNT(*) FROM attendance_logs l 
                JOIN students s ON l.student_id = s.student_id 
                WHERE date(l.timestamp, 'localtime') = date('now', 'localtime') AND l.status = 'สาย'
            """).fetchone()[0]
            
            leave = conn.execute("""
                SELECT COUNT(*) FROM attendance_logs l 
                JOIN students s ON l.student_id = s.student_id 
                WHERE date(l.timestamp, 'localtime') = date('now', 'localtime') AND l.status = 'ลา'
            """).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM students WHERE department = ?", (dept,)).fetchone()[0]
            
            present = conn.execute("""
                SELECT COUNT(*) FROM attendance_logs l 
                JOIN students s ON l.student_id = s.student_id 
                WHERE date(l.timestamp, 'localtime') = date('now', 'localtime') AND s.department = ? 
                AND (l.status = 'มาเรียน' OR l.status IS NULL OR l.status = '')
            """, (dept,)).fetchone()[0]
            
            late = conn.execute("""
                SELECT COUNT(*) FROM attendance_logs l 
                JOIN students s ON l.student_id = s.student_id 
                WHERE date(l.timestamp, 'localtime') = date('now', 'localtime') AND s.department = ? AND l.status = 'สาย'
            """, (dept,)).fetchone()[0]
            
            leave = conn.execute("""
                SELECT COUNT(*) FROM attendance_logs l 
                JOIN students s ON l.student_id = s.student_id 
                WHERE date(l.timestamp, 'localtime') = date('now', 'localtime') AND s.department = ? AND l.status = 'ลา'
            """, (dept,)).fetchone()[0]
            
        accounted = present + late + leave
        absent = total - accounted
        if absent < 0: absent = 0
        
        return jsonify({"total": total, "present": present, "late": late, "leave": leave, "absent": absent})
    except Exception as e:
        return jsonify({"total": 0, "present": 0, "late": 0, "leave": 0, "absent": 0})
    finally:
        conn.close()

if __name__ == '__main__': 
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)