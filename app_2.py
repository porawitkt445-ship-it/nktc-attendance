from flask import Blueprint, request, jsonify, session
import sqlite3
from datetime import datetime

# สร้าง Blueprint ชื่อ app_2_bp เพื่อนำไปเชื่อมกับ app.py ตัวหลัก
app_2_bp = Blueprint('app_2', __name__)

# ฟังก์ชันเชื่อมต่อฐานข้อมูลสำหรับใช้ในไฟล์นี้
def connect_db(): 
    return sqlite3.connect("attendance.db")

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