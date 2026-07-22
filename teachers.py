# teachers.py - จัดการระบบบัญชีครูและเข้าสู่ระบบ
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
import sqlite3

teachers_bp = Blueprint('teachers', __name__)

def connect_db():
    return sqlite3.connect("attendance.db")

def init_teachers_db():
    conn = connect_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS teachers (
        username TEXT PRIMARY KEY, password TEXT, 
        prefix TEXT, firstname TEXT, lastname TEXT, 
        position TEXT, academic_standing TEXT, 
        department TEXT, id_card TEXT, room TEXT, 
        birthdate TEXT, profile_img TEXT
    )''')
    cur = conn.execute("SELECT COUNT(*) FROM teachers")
    if cur.fetchone()[0] == 0:
        # ✅ เซ็ตข้อมูลเริ่มต้นให้ว่างเปล่า (เหมือนแอดมิน) ให้ครูไปกรอกเองที่หน้าโปรไฟล์
        conn.execute("INSERT INTO teachers VALUES ('JB01', '123456', '-', 'สุรพงษ์', 'ชัยจันทร์', 'ครูอัตราจ้าง', '-', '', '', '', '', '')")
        conn.execute("INSERT INTO teachers VALUES ('Elec01', '123456', '-', 'สมหญิง', 'รักเรียน', 'ครู', '-', '', '', '', '', '')")
        conn.execute("INSERT INTO teachers VALUES ('admin', '1234', '-', 'ผู้ดูแลระบบ', 'ส่วนกลาง', 'แอดมิน', '-', '', '', '', '', '')")
    conn.commit()
    conn.close()

@teachers_bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST': 
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = connect_db()
        cur = conn.execute("SELECT prefix, firstname, lastname, room, department FROM teachers WHERE username = ? AND password = ?", (username, password))
        teacher = cur.fetchone()
        conn.close()
        
        if teacher:
            session['username'] = username
            session['teacher_name'] = f"{teacher[1]} {teacher[2]}"
            session['teacher_room'] = teacher[3] if teacher[3] else "-"
            session['department'] = teacher[4] if teacher[4] else "-"
            return redirect(url_for('index'))
        else:
            return render_template('login.html')
            
    return render_template('login.html')

@teachers_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('teachers.login_page'))

@teachers_bp.route('/profile')
def profile_page():
    if 'username' not in session: return redirect(url_for('teachers.login_page'))
    
    conn = connect_db()
    cur = conn.execute("SELECT prefix, firstname, lastname, position, academic_standing, department, id_card, room, birthdate, profile_img FROM teachers WHERE username = ?", (session['username'],))
    teacher_data = cur.fetchone()
    conn.close()

    if teacher_data:
        prefix, firstname, lastname, position, academic_standing, dept, id_card, room, birthdate, profile_img = teacher_data
    else:
        prefix = firstname = lastname = position = academic_standing = dept = id_card = room = birthdate = profile_img = ""

    from departments import get_class_list
    class_list = get_class_list(dept)
    dept_list = [
        "เทคโนโลยีสารสนเทศ", "อิเล็กทรอนิกส์", "ช่างยนต์", "ช่างกลโรงงาน",
        "ช่างไฟฟ้ากำลัง", "ช่างก่อสร้าง", "โลจิสติกส์", "เทคนิคคอมพิวเตอร์", "ทุกแผนก"
    ]
    
    return render_template('profile.html', 
                           prefix=prefix, firstname=firstname, lastname=lastname,
                           position=position, academic_standing=academic_standing,
                           department=dept, id_card=id_card, teacher_room=room,
                           birthdate=birthdate, profile_img=profile_img, 
                           class_list=class_list, dept_list=dept_list)

@teachers_bp.route('/api/update_profile', methods=['POST'])
def update_profile():
    if 'username' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    try:
        advising_class = data.get('advising_class', '')
        if isinstance(advising_class, list):
            advising_class = ", ".join(advising_class)

        conn = connect_db()
        conn.execute("""
            UPDATE teachers SET 
            prefix=?, firstname=?, lastname=?, position=?, academic_standing=?, 
            department=?, id_card=?, room=?, birthdate=?, profile_img=? 
            WHERE username=?
        """, (data['prefix'], data['firstname'], data['lastname'], data['position'], 
              data['academic_standing'], data['department'], data['id_card'], 
              advising_class, data['birthdate'], data.get('profile_img', ''), session['username']))
        conn.commit(); conn.close()
        
        session['teacher_name'] = f"{data['firstname']} {data['lastname']}"
        session['department'] = data['department']
        session['teacher_room'] = advising_class
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})