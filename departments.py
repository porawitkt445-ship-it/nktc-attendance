from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
import sqlite3

# 1. ประกาศตัวแปร Blueprint เสมือนสร้างแอปย่อยอันที่ 2
departments_bp = Blueprint('departments', __name__)

def connect_db(): 
    return sqlite3.connect("attendance.db")

def get_class_list(department):
    # รายชื่อแผนกทั้งหมดในวิทยาลัย
    departments = [
        "เทคโนโลยีสารสนเทศ", "อิเล็กทรอนิกส์", "ช่างยนต์", "ช่างกลโรงงาน",
        "ช่างไฟฟ้ากำลัง", "ช่างก่อสร้าง", "โลจิสติกส์", "เทคนิคคอมพิวเตอร์"
    ]
    
    classes_map = {}
    grades = ["ปวช.1", "ปวช.2", "ปวช.3", "ปวส.1", "ปวส.2"]
    
    # สร้างรายชื่อห้องแบบอัตโนมัติ: ชั้นละ 5 ห้อง (/1 ถึง /5) ของทุกระดับชั้น
    for dept in departments:
        dept_classes = []
        for grade in grades:
            for room_no in range(1, 6): # ห้อง 1 ถึง 5
                dept_classes.append(f"{grade}/{room_no}-{dept}")
        classes_map[dept] = dept_classes
    
    # ถ้าเป็น "ทุกแผนก" ให้รวมห้องทั้งหมดทุกแผนกมาแสดง
    if department == "ทุกแผนก":
        all_classes = []
        for dept_classes in classes_map.values():
            all_classes.extend(dept_classes)
        return all_classes
        
    # คืนค่าตามแผนกที่ระบุ (ถ้าไม่เจอให้ดึงแผนกเทคโนโลยีสารสนเทศเป็นค่าเริ่มต้น)
    return classes_map.get(department, classes_map["เทคโนโลยีสารสนเทศ"])

# 2. หน้าหลักของแอปย่อย (สำหรับดูสถิติจำนวนเด็กแต่ละแผนก)
@departments_bp.route('/departments-dashboard')
def dept_dashboard():
    if 'username' not in session: 
        return redirect(url_for('teachers.login_page'))
        
    conn = connect_db()
    rows = conn.execute("SELECT department, COUNT(*) FROM students GROUP BY department").fetchall()
    conn.close()
    
    dept_stats = [{"department": r[0], "total_students": r[1]} for r in rows]
    
    return render_template('departments.html', 
                           dept_stats=dept_stats,
                           department=session.get('department'),
                           teacher_name=session.get('teacher_name'))

# 3. API สำหรับดึงรายชื่อแผนกทั้งหมดที่มีในระบบ
@departments_bp.route('/api/departments-list')
def get_departments():
    conn = connect_db()
    rows = conn.execute("SELECT DISTINCT department FROM students").fetchall()
    conn.close()
    return jsonify([r[0] for r in rows])

# เพิ่ม API นี้ในไฟล์ departments.py
@departments_bp.route('/api/classes/<path:department>')
def api_get_classes(department):
    classes = get_class_list(department)
    return jsonify(classes)