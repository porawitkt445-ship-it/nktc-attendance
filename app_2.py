from flask import Blueprint, request, jsonify, session
import sqlite3
import time  # 🟢 เพิ่มสำหรับใช้จับเวลา Cooldown
from datetime import datetime, timedelta  # 🟢 เพิ่ม timedelta สำหรับคำนวณเวลาไทย

# สร้าง Blueprint ชื่อ app_2_bp เพื่อนำไปเชื่อมกับ app.py ตัวหลัก
app_2_bp = Blueprint('app_2', __name__)

# ฟังก์ชันเชื่อมต่อฐานข้อมูลสำหรับใช้ในไฟล์นี้
def connect_db(): 
    return sqlite3.connect("attendance.db")

# =======================================================
# 🟢 ย้ายระบบป้องกันการสแกนซ้ำ และ เช็คสาย มาไว้ที่นี่
# =======================================================
scanned_students = {}
SCAN_COOLDOWN = 10 # หน่วงเวลา 10 วินาที

def log_attendance(student_id, backup_callback=None):
    current_time = time.time()
    
    # 1. เช็ค Cooldown ป้องกันการสแกนรัวๆ
    if student_id in scanned_students:
        if current_time - scanned_students[student_id] < SCAN_COOLDOWN:
            return 
            
    try:
        conn = connect_db()
        cur = conn.execute("""
            SELECT id FROM attendance_logs 
            WHERE student_id = ? AND date(timestamp, '+7 hours') = date('now', '+7 hours')
        """, (student_id,))
        
        row = cur.fetchone()
        
        if not row:
            # 2. ดึงเวลาปัจจุบัน (เทียบเป็นเวลาไทย +7 ชั่วโมง)
            local_now = datetime.utcnow() + timedelta(hours=7)
            
            # 3. เช็คเวลาว่าเกิน 08:30 หรือไม่
            if local_now.hour > 8 or (local_now.hour == 8 and local_now.minute >= 30):
                attendance_status = 'สาย'
            else:
                attendance_status = 'มาเรียน'
                
            # 4. บันทึกสถานะลงฐานข้อมูล
            conn.execute("INSERT INTO attendance_logs (student_id, status) VALUES (?, ?)", (student_id, attendance_status))
            conn.commit()
            
        scanned_students[student_id] = current_time
        conn.close()
        
        # 5. เรียกใช้ระบบ Backup กลับไปที่ app.py (ถ้ามีการส่งมา)
        if backup_callback:
            backup_callback()
            
    except sqlite3.Error as e:
        print(f"Database error: {e}")
# =======================================================


@app_2_bp.route('/api/attendance-summary')
def get_attendance_summary():
    dept = session.get('department', '')
    month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
    conn = connect_db()
    
    try:
        # ดึงรายชื่อนักเรียนทั้งหมด
        if dept == 'ทุกแผนก':
            students = conn.execute("SELECT student_id, name, class_group FROM students ORDER BY class_group, student_id").fetchall()
        else:
            students = conn.execute("SELECT student_id, name, class_group FROM students WHERE department = ? ORDER BY class_group, student_id", (dept,)).fetchall()
            
        summary_data = []
        
        # วนลูปหาข้อมูลของแต่ละคนในเดือนนั้นๆ
        for s in students:
            s_id = s[0]
            s_name = s[1]
            s_class = s[2]
            
            # นับจำนวนครั้งในแต่ละสถานะของเดือนที่เลือก
            logs = conn.execute(f"""
                SELECT status, COUNT(*) FROM attendance_logs 
                WHERE student_id = ? AND strftime('%Y-%m', datetime(timestamp, '+7 hours')) = '{month_str}'
                GROUP BY status
            """, (s_id,)).fetchall()
            
            # กำหนดค่าเริ่มต้น
            counts = {'มาเรียน': 0, 'ลา': 0, 'ขาด': 0, 'สาย': 0, 'ฝึกงาน': 0}
            
            # อัปเดตค่าจากฐานข้อมูล
            for status, count in logs:
                # กรณีสถานะว่าง หรือไม่ระบุ ให้นับเป็นมาเรียน
                if not status or status == '': counts['มาเรียน'] += count
                elif status in counts: counts[status] += count
            
            summary_data.append({
                "student_id": s_id,
                "name": s_name,
                "class_group": s_class,
                "present": counts['มาเรียน'],
                "leave": counts['ลา'],
                "absent": counts['ขาด'],
                "late": counts['สาย'],
                "intern": counts['ฝึกงาน']
            })
            
        return jsonify(summary_data)
        
    except Exception as e:
        print("Error summary:", e)
        return jsonify([])
    finally:
        conn.close()