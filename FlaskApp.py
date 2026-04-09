import csv
from flask import Flask, render_template, request, redirect, session, send_from_directory, Response, jsonify
import os, random, sqlite3, qrcode, io, base64
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import jsonify, request
from db import fetchone, fetchall, execute
from supabase import create_client, Client
import mimetypes
import uuid
import smtplib
from email.mime.text import MIMEText
import requests

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# ---------------- CONFIG ----------------
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")  # use service role key on the server
SUPABASE_BUCKET = "visitor-ids"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------- DATABASES ----------------
def init_visitor_database():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            reason TEXT NOT NULL,
            person_to_visit TEXT NOT NULL,
            department TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            visit_time TEXT NOT NULL,
            email TEXT NOT NULL,
            valid_id TEXT,
            time_in TEXT,
            time_out TEXT,
            status TEXT DEFAULT 'Pending',  -- Pending, Approved, Declined
            created_at TEXT NOT NULL,
            is_verified INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


def migrate_visitors_add_decision_fields():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(visitors)")
    cols = [row[1] for row in cursor.fetchall()]

    # Add missing columns safely
    if "decision_note" not in cols:
        cursor.execute("ALTER TABLE visitors ADD COLUMN decision_note TEXT")

    if "decided_by" not in cols:
        cursor.execute("ALTER TABLE visitors ADD COLUMN decided_by TEXT")

    if "decided_at" not in cols:
        cursor.execute("ALTER TABLE visitors ADD COLUMN decided_at TEXT")

    conn.commit()
    conn.close()


def init_admin_database():
    conn = sqlite3.connect('admin.db')
    cursor = conn.cursor()

    # Create table (fresh installs)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,          -- admin, guard, dep_head
            department TEXT              -- NULL for admin/guard, e.g. BSIS/CRIM/BSA for dep_head
        )
    ''')

    # ✅ Migration: add department column if this DB was created before
    cursor.execute("PRAGMA table_info(admin)")
    cols = [row[1] for row in cursor.fetchall()]
    if "department" not in cols:
        cursor.execute("ALTER TABLE admin ADD COLUMN department TEXT")

    # Seed default accounts
    cursor.execute(
        'INSERT OR IGNORE INTO admin (username, password, role, department) VALUES (?, ?, ?, ?)',
        ('admin', '12345', 'admin', None)
    )
    cursor.execute(
        'INSERT OR IGNORE INTO admin (username, password, role, department) VALUES (?, ?, ?, ?)',
        ('guard', '12345', 'guard', None)
    )

    # Department heads
    cursor.execute(
        'INSERT OR IGNORE INTO admin (username, password, role, department) VALUES (?, ?, ?, ?)',
        ('bsis_head', '12345', 'dep_head', 'BSIS')
    )
    cursor.execute(
        'INSERT OR IGNORE INTO admin (username, password, role, department) VALUES (?, ?, ?, ?)',
        ('crim_head', '12345', 'dep_head', 'CRIM')
    )
    cursor.execute(
        'INSERT OR IGNORE INTO admin (username, password, role, department) VALUES (?, ?, ?, ?)',
        ('bsa_head', '12345', 'dep_head', 'BSA')
    )

    conn.commit()
    conn.close()



def init_homepage_database():
    conn = sqlite3.connect('visitors.db')  # same database as visitors
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS homepage_content (
            section TEXT PRIMARY KEY,
            content TEXT
        )
    ''')
    default_content = [
        ('about_paragraph1', 'La Concepcion College, Inc. (LCC) is founded in 1998, a non-sectarian higher education institution with a young nucleus of rich academic, cultural, and athletic achievements offering academic programs from Pre-Kindergarten, Elementary, Junior High School, Senior High School, Vocational, to College Courses, the school is strategically situated in the heart of the fast-growing City of San Jose del Monte, Bulacan, Philippines.'),
        ('about_paragraph2', 'The LCC Online Appointment System was developed to make scheduling visits and inquiries more convenient for students, parents, and visitors. Through this system, you can easily set appointments for admissions, consultations, and other school-related transactions—ensuring an organized and efficient experience for everyone.'),
        ('how_intro', 'To ensure a smooth and organized visit, all visitors must schedule online.'),
        ('how_step1', 'Complete the required details on the appointment form.'),
        ('how_step2', 'After submitting, a unique QR code will be generated.'),
        ('how_step3', 'Your request will be reviewed by administration.'),
        ('how_step4', 'Present your QR code to security upon arrival.'),
        ('contact_phone', '(044) 762-36-60'),
        ('contact_phone_extra', '09276769921 – General Information'),
        ('contact_email', 'registrar@laconcepcioncollege.com'),
        ('contact_address', 'Kaypian Road, corner Quirino St, San Jose del Monte City, Bulacan, 3023'),  # ✅ comma here

        # ✅ NEW: editable Terms & Conditions
        ('terms_title', 'Terms and Conditions'),
        ('terms_body',
         "Welcome to La Concepcion College's Online Appointment System.\n\n"
         "• Purpose of the System. The GATE-PASS system is designed to streamline visitor entry, enhance campus security, and provide an efficient appointment and tracking process within La Concepcion College. The system collects data to authenticate identity, record visit logs, and support administrative operations.\n"
         "• Collection of Personal Information. To use the system, users may be required to provide personal information such as\n"
         " -Full Name\n"
         " -Email Address\n" 
         " -Valid ID\n"
         "• All information collected is necessary for proper identity verification and security monitoring.\n"
         "• Legal Basis for Processing (RA 10173). All personal data shall be processed in accordance with the Data Privacy Act of 2012 (RA 10173) and its Implementing Rules and Regulations. Processing is based on:\n"
         " -User Consent\n"
         " -Legitimate interest of the institution\n"
         " -Compliance with regulatory and security requirements\n"
         "• Use of Collected Data. The collected data will be used exclusively for:\n"
         " -Visitor verification and campus entry approval\n"
         " -Appointment scheduling and confirmation\n"
         " -Real-time and historical visitor tracking\n"
         " -Security monitoring and record-keeping\n"
         " -Institutional reporting and audit purposes\n"
         "• No data will be used for purposes beyond those stated without your explicit consent.\n"
         "• Data Sharing and Disclosure. Your personal information will not be sold or shared with third parties. Data may only be disclosed:\n"
         " -When required by law or government authorities\n"
         " -When necessary for safety, security, or institutional operations\n"
         " -When authorized by the data subject\n"
         "• Data Storage, Retention, and Security Measures. All personal data is stored securely within the institution’s authorized servers and protected through:\n"
         " -Encryption\n"
         " -Access controls\n"
         " -Secure data transmission\n"
         " -Regular system audits\n"
         "• Rights of Data Subjects. Under RA 10173, all users have the right to:\n"
         " -Request corrections or updates\n"
         " -Withdraw consent at any time\n"
         " -Object to the processing of their data\n"
         " -Request deletion of data, subject to legal and institutional limits\n"
         " -File a complaint with the National Privacy Commission (NPC)\n"
         "• User Responsibilities. By using the GATE-PASS system, users agree to:\n"
         " -Provide accurate and truthful information\n"
         " -Keep QR codes and login credentials confidential\n"
         " -Use the system only for lawful and intended purposes\n"
         "• Consent\n"
         "• By accessing and using the GATE-PASS system, you voluntarily consent to the collection, processing, and storage of your personal information as described in this Terms and Conditions.\n"

         ),
    ]
    for section, content in default_content:
        cursor.execute("INSERT OR IGNORE INTO homepage_content (section, content) VALUES (?, ?)", (section, content))
    conn.commit()
    conn.close()

def init_settings_database():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # default = OFF
    cursor.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("TEST_MODE", "0")
    )

    conn.commit()
    conn.close()


def init_notifications_database():
    conn = sqlite3.connect("visitors.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_role TEXT NOT NULL,           -- "admin" | "guard" | "dep_head"
            target_department TEXT,              -- nullable, for dep_head notifications
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            type TEXT NOT NULL,                  -- "NEW_PENDING" | "APPROVED" | "DECLINED" | "TIME_IN" | "TIME_OUT"
            visitor_id INTEGER,
            created_at TEXT NOT NULL,
            is_read INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


# Initialize databases
init_visitor_database()
init_admin_database()
init_homepage_database()
init_settings_database()
migrate_visitors_add_decision_fields()
init_notifications_database()


# ---------------- EMAIL SETTINGS ----------------
# Make sure you set these in your .env or system environment variables
EMAIL_USER = os.environ.get("EMAIL_USER")       # Verified Brevo sender email
EMAIL_API_KEY = os.environ.get("EMAIL_PASS")    # Brevo API key


def send_email_otp(to_email, otp):
    """
    Sends OTP email using Brevo API.
    Returns: (success: bool, message: str)
    """
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": EMAIL_API_KEY,
        "content-type": "application/json"
    }
    payload = {
        "sender": {"name": "Capstone Project", "email": EMAIL_USER},
        "to": [{"email": to_email}],
        "subject": "Your OTP Code",
        "htmlContent": f"<html><body><p>Your OTP code is: <b>{otp}</b></p></body></html>"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 201:
            return True, "Email sent successfully"
        else:
            return False, f"Failed to send: {response.text}"
    except Exception as e:
        return False, str(e)


def generate_otp():
    return str(random.randint(100000, 999999))

def is_test_mode():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("SELECT value FROM settings WHERE key='TEST_MODE'")
    row = cursor.fetchone()

    conn.close()

    return row and row[0] == "1"


def add_notification(
    target_role,
    title,
    body,
    type_,
    visitor_id=None,
    target_department=None
):
    created_at = datetime.now(ZoneInfo("Asia/Manila"))  # timestamptz

    execute("""
        insert into public.notifications
            (target_role, target_department, title, body, type, visitor_id, created_at, is_read)
        values
            (%s, %s, %s, %s, %s, %s, %s, false)
    """, (
        target_role,
        target_department,
        title,
        body,
        type_,
        visitor_id,
        created_at
    ))

def get_visitor_brief(visitor_id: int):
    row = fetchone("""
        select
            name,
            department,
            person_to_visit,
            reason,
            visit_date,
            visit_time,
            decision_note
        from public.visitors
        where id = %s
    """, (visitor_id,))

    if not row:
        return None

    return {
        "name": row["name"],
        "department": row["department"],
        "person_to_visit": row["person_to_visit"],
        "reason": row["reason"],
        "visit_date": str(row["visit_date"]),
        "visit_time": str(row["visit_time"]),
        "decision_note": row["decision_note"],
    }


# Used when we already have visitor info from DB
def build_notif_body(brief: dict) -> str:
    note = (brief.get("decision_note") or "").strip()
    note_line = f"\nNote: {note}" if note else ""

    return (
        f"{brief['name']} → {brief['person_to_visit']}\n"
        f"Reason: {brief['reason']}\n"
        f"Time and date of visit: {brief['visit_date']} {brief['visit_time']}"
        f"{note_line}"
    )

# Used when visitor info comes from form/session (Pending)
def build_notif_body_from_fields(
    name: str,
    person_to_visit: str,
    reason: str,
    visit_date: str,
    visit_time: str,
    note=None
) -> str:
    note = (note or "").strip()
    note_line = f"\nNote: {note}" if note else ""

    return (
        f"{name} → {person_to_visit}\n"
        f"Reason: {reason}\n"
        f"Time and date of visit: {visit_date} {visit_time}"
        f"{note_line}"
    )

def upload_id_to_supabase(file):
    if not file or not file.filename:
        return None

    original_name = secure_filename(file.filename)
    ext = os.path.splitext(original_name)[1].lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"valid_ids/{unique_name}"

    content_type = file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    file_bytes = file.read()
    file.seek(0)

    response = supabase.storage.from_(SUPABASE_BUCKET).upload(
        storage_path,
        file_bytes,
        {"content-type": content_type}
    )

    return storage_path



def build_guard_scan_body(brief: dict, action: str, actual_time: str) -> str:
    if action == "TIME_IN":
        first_line = f"{brief['name']} is already at the premises."
        actual_line = f"Actual Arrival: {actual_time}"
    else:
        first_line = f"{brief['name']} has already left the premises."
        actual_line = f"Actual Exit: {actual_time}"

    return (
        f"{first_line}\n"
        f"Person to Visit: {brief['person_to_visit']}\n"
        f"Reason: {brief['reason']}\n"
        f"Scheduled Visit: {brief['visit_date']} {brief['visit_time']}\n"
        f"{actual_line}"
    )


def send_custom_visitor_email(to_email, subject, message_body):
    if not EMAIL_USER:
        return False, "EMAIL_USER is not set"

    if not EMAIL_API_KEY:
        return False, "EMAIL_PASS (Brevo API key) is not set"

    url = "https://api.brevo.com/v3/smtp/email"

    headers = {
        "accept": "application/json",
        "api-key": EMAIL_API_KEY,
        "content-type": "application/json"
    }

    html_content = f"""
    <html>
    <body>
        <p>{message_body.replace('\n', '<br>')}</p>
        <br>
        <p>Best regards,<br>La Concepcion College</p>
    </body>
    </html>
    """

    payload = {
        "sender": {"name": "La Concepcion College", "email": EMAIL_USER},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }

    try:
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 201:
            return True, "Email sent"
        else:
            print("Brevo error:", response.text)
            return False, response.text

    except Exception as e:
        print("custom visitor email error:", e)
        return False, str(e)


# ---------------- ROUTES ----------------

# Homepage
@app.route('/')
def index():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()
    cursor.execute("SELECT section, content FROM homepage_content")
    rows = cursor.fetchall()
    homepage_content = {row[0]: row[1] for row in rows}
    conn.close()
    return render_template('index.html', homepage=homepage_content)


# Appointment form
@app.route('/appointment')
def appointment():
    if not session.get('accepted_terms'):
        return redirect('/terms')
    return render_template('qr_form.html', test_mode=is_test_mode())


@app.route('/terms')
def terms():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()
    cursor.execute("SELECT section, content FROM homepage_content")
    rows = cursor.fetchall()
    content = {row[0]: row[1] for row in rows}
    conn.close()

    return render_template(
        'terms.html',
        terms_title=content.get('terms_title', 'Terms and Conditions'),
        terms_body=content.get('terms_body', '')
    )

@app.route('/accept_terms', methods=['POST'])
def accept_terms():
    session['accepted_terms'] = True
    return redirect('/appointment')

# Send OTP for verification
@app.route('/send_verification', methods=['POST'])
def send_verification():
    name = request.form['name'].strip()
    email = request.form['email'].strip()
    visit_date = request.form['visit_date'].strip()
    visit_time = request.form['visit_time'].strip()

    # Normalize time to HH:MM:SS for Postgres time type (safer)
    if len(visit_time) == 5:
        visit_time = visit_time + ":00"

    # ✅ Enforce date and time rules ONLY if TEST MODE is OFF
    if not is_test_mode():
        today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()
        selected_date = datetime.strptime(visit_date, "%Y-%m-%d").date()

        if selected_date <= today_ph:
            return render_template(
                "Error.html",
                message="⚠️ Same-day appointments are not allowed. Please choose tomorrow or later."
            )

        try:
            selected_time = datetime.strptime(visit_time, "%H:%M:%S").time()
        except ValueError:
            return render_template("Error.html", message="⚠️ Invalid time format.")

        start_time = datetime.strptime("09:00:00", "%H:%M:%S").time()
        end_time = datetime.strptime("16:00:00", "%H:%M:%S").time()

        if selected_time < start_time or selected_time > end_time:
            return render_template(
                "Error.html",
                message="⚠️ Visiting hours are only from 9:00 AM to 4:00 PM. Please select a valid time."
            )

    # ✅ Duplicate appointment check in SUPABASE
    # (same name + date + time)
    exists = fetchone("""
        select id
        from public.visitors
        where name = %s
          and visit_date = %s
          and visit_time = %s
        limit 1
    """, (name, visit_date, visit_time))

    if exists:
        return render_template(
            'Error.html',
            message="⚠️ You already have an appointment for this date and time."
        )

    # Store visitor info in session (used by verify_otp)
    session['visitor_info'] = {
        'name': name,
        'reason': request.form['reason'].strip(),
        'person_to_visit': request.form['person_to_visit'].strip(),
        'department': request.form['department'].strip(),
        'visit_date': visit_date,
        'visit_time': visit_time,  # now HH:MM:SS
        'email': email
    }

    # Save uploaded ID filename (file is still stored on Render disk)
    file = request.files.get('valid_id')
    if file and file.filename:
        try:
            storage_path = upload_id_to_supabase(file)
            session['valid_id_filename'] = storage_path
        except Exception as e:
            print("Supabase ID upload error:", e)
            return render_template("Error.html", message="❌ Failed to upload valid ID. Please try again.")
    else:
        session['valid_id_filename'] = None

    # OTP
    otp = generate_otp()
    session['otp'] = otp
    session['otp_timestamp'] = datetime.now().timestamp()

    success, msg = send_email_otp(email, otp)

    if success:
        return render_template('verify_email.html', email=email)

    error_message = f"❌ Failed to send verification email. {msg}"
    print(error_message)
    return render_template('Error.html', message=error_message)


# Verify OTP
@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    entered_otp = request.form.get('otp', '').strip()
    stored_otp = session.get('otp')
    otp_timestamp = session.get('otp_timestamp')

    # Check if OTP exists
    if not stored_otp:
        return render_template('Error.html', message="❌ OTP session expired. Please request a new code.")

    # Check expiry (10 minutes)
    if otp_timestamp:
        elapsed_time = datetime.now().timestamp() - otp_timestamp
        if elapsed_time > 600:
            return render_template('Error.html', message="❌ OTP has expired. Please request a new code.")

    if entered_otp != stored_otp:
        return render_template('Error.html', message="❌ Invalid OTP. Please try again or request a new code.")

    visitor_info = session.get('visitor_info')
    filename = session.get('valid_id_filename')

    if not visitor_info:
        return render_template('Error.html', message="❌ Session expired. Please submit the appointment form again.")

    try:
        # ✅ Insert into SUPABASE (public.visitors) and get the new ID
        row = fetchone("""
            insert into public.visitors
                (name, reason, person_to_visit, department,
                 visit_date, visit_time, email, valid_id,
                 status, is_verified)
            values
                (%s, %s, %s, %s,
                 %s, %s, %s, %s,
                 'Pending', true)
            returning id
        """, (
            visitor_info['name'],
            visitor_info['reason'],
            visitor_info['person_to_visit'],
            visitor_info['department'],
            visitor_info['visit_date'],   # 'YYYY-MM-DD' ok
            visitor_info['visit_time'],   # 'HH:MM' ok
            visitor_info['email'],
            filename
        ))

        visitor_id = row["id"]
        session["visitor_id"] = int(visitor_id)
        session["verified_email"] = visitor_info["email"]

        # ✅ Optional: notify admin that there is a new pending appointment
        add_notification(
            target_role="admin",
            title="New Appointment Request",
            body=build_notif_body_from_fields(
                name=visitor_info["name"],
                person_to_visit=visitor_info["person_to_visit"],
                reason=visitor_info["reason"],
                visit_date=visitor_info["visit_date"],
                visit_time=visitor_info["visit_time"],
                note=None  # Pending has no decision note yet
            ),
            type_="PENDING",
            visitor_id=visitor_id
        )

        # Clear OTP
        session.pop('otp', None)
        session.pop('otp_timestamp', None)

        return render_template('pending_approval.html')

    except Exception as e:
        print("verify_otp error:", e)
        return render_template('Error.html', message="❌ Server error. Please try again.")


# QR Generation
@app.route('/generate_qr_form')
def generate_qr_form():
    visitor_info = session.get('visitor_info')
    filename = session.get('valid_id_filename')
    if not visitor_info:
        return redirect('/')
    visitor_id = session.get("visitor_id")
    qr_link = f"https://emailandmobileapp.onrender.com/generate_qr/{visitor_id}" if visitor_id else "N/A"
    qr_data = (
        f"VISITOR_ID:{visitor_id if visitor_id else 'N/A'}\n"
        f"QR_LINK:{qr_link}\n"
        f"Name: {visitor_info['name']}\n"
        f"Reason: {visitor_info['reason']}\n"
        f"Person to Visit: {visitor_info['person_to_visit']}\n"
        f"Department: {visitor_info['department']}\n"
        f"Date: {visitor_info['visit_date']}\n"
        f"Time: {visitor_info['visit_time']}\n"
        f"Email: {visitor_info['email']}\n"
        f"Valid ID: {filename if filename else 'None'}"
    )
    qr = qrcode.make(qr_data)
    buffer = io.BytesIO()
    qr.save(buffer)
    qr_code = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return render_template('qr_result.html', qr_code=qr_code, visitor_info=visitor_info, valid_id=filename)

@app.route('/generate_qr/<int:visitor_id>')
def generate_qr_by_id(visitor_id):
    # 1) Try Supabase/Postgres first
    row = fetchone("""
        select name, reason, person_to_visit, department, visit_date, visit_time, email, valid_id
        from public.visitors
        where id = %s
    """, (visitor_id,))

    if row:
        visitor_info = {
            "name": row["name"],
            "reason": row["reason"],
            "person_to_visit": row["person_to_visit"],
            "department": row["department"],
            "visit_date": str(row["visit_date"]),
            "visit_time": str(row["visit_time"]),
            "email": row["email"]
        }
        filename = row["valid_id"]
    else:
        # 2) Optional fallback to old SQLite data
        conn = sqlite3.connect('visitors.db')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, reason, person_to_visit, department, visit_date, visit_time, email, valid_id
            FROM visitors WHERE id=?
        """, (visitor_id,))
        visitor = cursor.fetchone()
        conn.close()

        if not visitor:
            return "❌ Visitor not found", 404

        visitor_info = {
            "name": visitor[0],
            "reason": visitor[1],
            "person_to_visit": visitor[2],
            "department": visitor[3],
            "visit_date": visitor[4],
            "visit_time": visitor[5],
            "email": visitor[6],
        }
        filename = visitor[7]

    qr_link = f"https://emailandmobileapp.onrender.com/generate_qr/{visitor_id}"

    qr_data = (
        f"VISITOR_ID:{visitor_id}\n"
        f"QR_LINK:{qr_link}\n"
        f"Name: {visitor_info['name']}\n"
        f"Reason: {visitor_info['reason']}\n"
        f"Person to Visit: {visitor_info['person_to_visit']}\n"
        f"Department: {visitor_info['department']}\n"
        f"Date: {visitor_info['visit_date']}\n"
        f"Time: {visitor_info['visit_time']}\n"
        f"Email: {visitor_info['email']}\n"
        f"Valid ID: {filename if filename else 'None'}"
    )

    qr = qrcode.make(qr_data)
    buffer = io.BytesIO()
    qr.save(buffer)
    qr_code = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return render_template('qr_result.html', qr_code=qr_code, visitor_info=visitor_info, valid_id=filename)


# View uploaded file
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/view-id/<path:file_path>')
def view_id(file_path):
    if 'admin' not in session:
        return redirect('/admin/login')

    try:
        signed = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(file_path, 3600)
        signed_url = signed.get("signedURL") or signed.get("signed_url")

        if not signed_url:
            return "❌ Could not generate signed URL", 404

        return redirect(signed_url)
    except Exception as e:
        print("view_id error:", e)
        return "❌ File not found", 404


# ---------------- ADMIN ROUTES ----------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('admin.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin WHERE username=? AND password=?", (username, password))
        admin = cursor.fetchone()
        conn.close()
        if admin:
            session['admin'] = username
            return redirect('/admin/dashboard')
        else:
            return render_template('admin_login.html', error="Invalid credentials.")
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/admin/login')


# Admin dashboard
@app.route('/admin/dashboard', methods=['GET'])
def admin_dashboard():
    if 'admin' not in session:
        return redirect('/admin/login')

    filter_type = request.args.get('filter')

    where_sql = ""
    if filter_type == 'week':
        where_sql = "where created_at >= (now() - interval '7 days')"
    elif filter_type == 'month':
        where_sql = "where created_at >= (now() - interval '30 days')"
    elif filter_type == 'year':
        where_sql = "where created_at >= (now() - interval '365 days')"

    rows = fetchall(f"""
        select
            id, name, reason, person_to_visit, department,
            visit_date, visit_time, email, valid_id,
            time_in, time_out, status, created_at
        from public.visitors
        {where_sql}
        order by id desc
    """)

    visitors = []
    for r in rows:
        visitors.append((
            r["id"],                                        # [0]
            r["name"],                                      # [1]
            r["reason"],                                    # [2]
            r["person_to_visit"],                           # [3]
            r["department"],                                # [4]
            str(r["visit_date"]) if r["visit_date"] else "",# [5]
            str(r["visit_time"]) if r["visit_time"] else "",# [6]
            r["email"],                                     # [7]
            r["valid_id"],                                  # [8]
            r["time_in"].isoformat() if r["time_in"] else "",    # [9]
            r["time_out"].isoformat() if r["time_out"] else "",  # [10]
            r["status"],                                    # [11]
            r["created_at"].isoformat() if r["created_at"] else "" # [12]
        ))

    return render_template(
        'admin_dashboard.html',
        visitors=visitors,
        filter_type=filter_type,
        test_mode=is_test_mode()
    )

@app.route('/admin/approve/<int:visitor_id>')
def approve_visitor(visitor_id):
    if 'admin' not in session:
        return redirect('/admin/login')

    decided_by = session.get("admin", "admin")
    decided_at = datetime.now(ZoneInfo("Asia/Manila"))

    execute("""
        update public.visitors
        set status='Approved',
            decided_by=%s,
            decided_at=%s
        where id=%s
    """, (decided_by, decided_at, visitor_id))

    # ✅ delete old APPROVED/DECLINED notifications FIRST
    execute("""
        delete from public.notifications
        where visitor_id = %s
          and type in ('APPROVED', 'DECLINED')
    """, (visitor_id,))

    # ✅ create NEW notifications with full details
    brief = get_visitor_brief(visitor_id)
    if brief:
        add_notification(
            target_role="guard",
            title="Visitor Approved",
            body=build_notif_body(brief),
            type_="APPROVED",
            visitor_id=visitor_id
        )

        add_notification(
            target_role="dep_head",
            target_department=brief["department"],
            title="Visitor Approved",
            body=build_notif_body(brief),
            type_="APPROVED",
            visitor_id=visitor_id
        )

    # Email QR link (same as yours)
    row = fetchone("select email from public.visitors where id=%s", (visitor_id,))
    if row:
        email = row["email"]
        qr_link = f"https://emailandmobileapp.onrender.com/generate_qr/{visitor_id}"

        subject = "Visit Approved - La Concepcion College"
        message_body = f"""
    Your visit has been APPROVED.

    Please save your QR code here:
    {qr_link}
    """

        success, msg = send_custom_visitor_email(email, subject, message_body)

        if not success:
            print("Approval email failed:", msg)

    return redirect('/admin/dashboard')


@app.route('/admin/decline/<int:visitor_id>')
def decline_visitor(visitor_id):
    if 'admin' not in session:
        return redirect('/admin/login')

    decided_by = session.get("admin", "admin")
    decided_at = datetime.now(ZoneInfo("Asia/Manila"))

    execute("""
        update public.visitors
        set status='Declined',
            decided_by=%s,
            decided_at=%s
        where id=%s
    """, (decided_by, decided_at, visitor_id))

    execute("""
        delete from public.notifications
        where visitor_id = %s
          and type in ('APPROVED', 'DECLINED')
    """, (visitor_id,))

    brief = get_visitor_brief(visitor_id)
    if brief:
        add_notification(
            target_role="guard",
            title="Visitor Declined",
            body=build_notif_body(brief),
            type_="DECLINED",
            visitor_id=visitor_id
        )

        add_notification(
            target_role="dep_head",
            target_department=brief["department"],
            title="Visitor Declined",
            body=build_notif_body(brief),
            type_="DECLINED",
            visitor_id=visitor_id
        )

    # email (same as yours)
    row = fetchone("select email from public.visitors where id=%s", (visitor_id,))
    if row:
        email = row["email"]

        subject = "Visit Declined - La Concepcion College"
        message_body = "We are sorry, your visit request was DECLINED."

        success, msg = send_custom_visitor_email(email, subject, message_body)

        if not success:
            print("Decline email failed:", msg)

    return redirect('/admin/dashboard')


# Download CSV
@app.route('/admin/download_csv')
def download_csv():
    if 'admin' not in session:
        return redirect('/admin/login')

    filter_type = request.args.get('filter')

    where_sql = ""
    if filter_type == 'week':
        where_sql = "where created_at >= (now() - interval '7 days')"
    elif filter_type == 'month':
        where_sql = "where created_at >= (now() - interval '30 days')"
    elif filter_type == 'year':
        where_sql = "where created_at >= (now() - interval '365 days')"

    rows = fetchall(f"""
        select
            id, name, reason, department, person_to_visit,
            visit_date, visit_time, email, valid_id,
            time_in, time_out, status, created_at
        from public.visitors
        {where_sql}
        order by id desc
    """)

    def generate():
        data = io.StringIO()
        writer = csv.writer(data)

        writer.writerow([
            'ID', 'Name', 'Reason', 'Department', 'Person to Visit',
            'Date', 'Time', 'Email', 'Valid ID',
            'Time In', 'Time Out', 'Status', 'Created At'
        ])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)

        for r in rows:
            writer.writerow([
                r["id"],
                r["name"],
                r["reason"],
                r["department"],
                r["person_to_visit"],
                str(r["visit_date"]) if r["visit_date"] else "",
                str(r["visit_time"]) if r["visit_time"] else "",
                r["email"],
                r["valid_id"] or "",
                r["time_in"].isoformat() if r["time_in"] else "",
                r["time_out"].isoformat() if r["time_out"] else "",
                r["status"],
                r["created_at"].isoformat() if r["created_at"] else "",
            ])
            yield data.getvalue()
            data.seek(0)
            data.truncate(0)

    filename = f"visitors_{filter_type if filter_type else 'all'}.csv"
    return Response(generate(), mimetype='text/csv',
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# Edit homepage content
@app.route('/admin/edit_homepage', methods=['GET', 'POST'])
def edit_homepage():
    if 'admin' not in session:
        return redirect('/admin/login')
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    if request.method == 'POST':
        for key, value in request.form.items():
            cursor.execute("REPLACE INTO homepage_content (section, content) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
        return redirect('/')

    cursor.execute("SELECT section, content FROM homepage_content")
    rows = cursor.fetchall()
    homepage_content = {row[0]: row[1] for row in rows}
    conn.close()
    return render_template('edit_homepage.html', homepage=homepage_content)


@app.route('/admin/toggle_test_mode')
def toggle_test_mode():
    if 'admin' not in session:
        return redirect('/admin/login')

    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    # read current
    cursor.execute("SELECT value FROM settings WHERE key='TEST_MODE'")
    row = cursor.fetchone()
    current = (row and row[0] == "1")

    # flip
    new_value = "0" if current else "1"
    cursor.execute(
        "UPDATE settings SET value=? WHERE key='TEST_MODE'",
        (new_value,)
    )

    conn.commit()
    conn.close()

    return redirect('/admin/dashboard')


@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"success": False, "message": "Missing username or password"}), 400

    row = fetchone(
        "select role, department from public.admin_accounts where username=%s and password=%s",
        (username, password)
    )

    if row:
        return jsonify({
            "success": True,
            "role": row["role"],
            "department": row["department"]
        })

    return jsonify({"success": False, "message": "Invalid credentials"}), 401


@app.route('/api/admin/visitors', methods=['GET'])
def api_admin_visitors():
    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()

    rows = fetchall("""
        select
            id,
            name,
            reason,
            department,
            person_to_visit,
            visit_date,
            visit_time,
            email,
            valid_id,
            status,
            time_in,
            time_out,
            created_at,
            decision_note,
            decided_by,
            decided_at
        from public.visitors
        order by visit_date desc, visit_time desc, id desc
    """)

    visitors = []
    for r in rows:
        visit_date = r["visit_date"]
        time_in = r["time_in"]

        derived_status = r["status"]

        if visit_date and visit_date < today_ph:
            if time_in is not None:
                derived_status = "Completed"
            else:
                derived_status = "No-show"

        visitors.append({
            "id": r["id"],
            "name": r["name"],
            "reason": r["reason"],
            "department": r["department"],
            "person_to_visit": r["person_to_visit"],
            "visit_date": str(visit_date) if visit_date else None,
            "visit_time": str(r["visit_time"]) if r["visit_time"] else None,
            "email": r["email"],
            "valid_id": r["valid_id"],
            "status": r["status"],                  # original DB status
            "derived_status": derived_status,       # computed display status
            "time_in": r["time_in"].isoformat() if r["time_in"] else None,
            "time_out": r["time_out"].isoformat() if r["time_out"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "decision_note": r["decision_note"],
            "decided_by": r["decided_by"],
            "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
        })

    return jsonify(visitors)

@app.route('/api/admin/approve/<int:visitor_id>', methods=['POST'])
def api_admin_approve(visitor_id):
    try:
        data = request.get_json(silent=True) or {}
        note = (data.get("note") or "").strip() or None

        decided_by = "admin"  # later: from auth token/session
        decided_at = datetime.now(ZoneInfo("Asia/Manila"))  # timestamptz-friendly

        # 1) Update visitor decision (Postgres)
        execute("""
            update public.visitors
            set status = 'Approved',
                decision_note = %s,
                decided_by = %s,
                decided_at = %s
            where id = %s
        """, (note, decided_by, decided_at, visitor_id))

        # 2) Remove old decision notifications for this visitor (Postgres)
        execute("""
            delete from public.notifications
            where visitor_id = %s
              and type in ('APPROVED', 'DECLINED')
        """, (visitor_id,))

        # 3) Create APPROVED notifications (your helpers)
        brief = get_visitor_brief(visitor_id)
        if brief:
            body_text = build_notif_body(brief)

            add_notification(
                target_role="guard",
                title="Visitor Approved",
                body=body_text,
                type_="APPROVED",
                visitor_id=visitor_id
            )

            add_notification(
                target_role="dep_head",
                target_department=brief["department"],
                title="Visitor Approved",
                body=body_text,
                type_="APPROVED",
                visitor_id=visitor_id
            )

        # 4) Get email from Postgres
        row = fetchone("select email from public.visitors where id = %s", (visitor_id,))
        if not row:
            return jsonify({"success": False, "message": "Visitor not found"}), 404

        email = row["email"]

        # 5) Email approved QR link
        qr_link = f"https://emailandmobileapp.onrender.com/generate_qr/{visitor_id}"

        message = Mail(
            from_email=EMAIL_ADDRESS,
            to_emails=email,
            subject="Visit Approved - La Concepcion College",
            html_content=f"""
                <p>Your visit has been <b>approved</b>.</p>
                <p>Please save your QR code here:</p>
                <a href="{qr_link}">{qr_link}</a>
            """
        )

        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            print("Approval email failed:", e)

        return jsonify({"success": True, "message": "Approved", "note_saved": bool(note)})

    except Exception as e:
        print("api_admin_approve error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/admin/decline/<int:visitor_id>', methods=['POST'])
def api_admin_decline(visitor_id):
    try:
        data = request.get_json(silent=True) or {}
        note = (data.get("note") or "").strip()

        decided_by = "admin"  # later from auth token/session
        decided_at = datetime.now(ZoneInfo("Asia/Manila"))  # timestamptz

        # 1) Update visitor decision
        execute("""
            update public.visitors
            set
                status = 'Declined',
                decision_note = %s,
                decided_by = %s,
                decided_at = %s
            where id = %s
        """, (
            note if note else None,
            decided_by,
            decided_at,
            visitor_id
        ))

        # 2) Remove old decision notifications for this visitor
        execute("""
            delete from public.notifications
            where visitor_id = %s
              and type in ('APPROVED','DECLINED')
        """, (visitor_id,))

        # 3) Get email
        row = fetchone("""
            select email
            from public.visitors
            where id = %s
        """, (visitor_id,))

        if not row:
            return jsonify({"success": False, "message": "Visitor not found"}), 404

        email = row["email"]

        # 4) Create DECLINED notifications
        brief = get_visitor_brief(visitor_id)
        if brief:
            body_text = build_notif_body(brief)

            add_notification(
                target_role="guard",
                title="Visitor Declined",
                body=body_text,
                type_="DECLINED",
                visitor_id=visitor_id
            )

            add_notification(
                target_role="dep_head",
                target_department=brief["department"],
                title="Visitor Declined",
                body=body_text,
                type_="DECLINED",
                visitor_id=visitor_id
            )

        # 5) Email (include note)
        note_html = f"<p><b>Reason / Note:</b> {note}</p>" if note else ""

        message = Mail(
            from_email=EMAIL_ADDRESS,
            to_emails=email,
            subject="Visit Declined - La Concepcion College",
            html_content=f"""
                <p>We are sorry, your visit request was <b>declined</b>.</p>
                {note_html}
            """
        )

        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            print("Decline email failed:", e)

        return jsonify({
            "success": True,
            "message": "Declined",
            "note_saved": bool(note)
        })

    except Exception as e:
        print("api_admin_decline error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500

# ---------------- ADMIN ACCOUNTS API ----------------

@app.route("/api/admin/accounts", methods=["GET"])
def api_admin_accounts_list():
    conn = sqlite3.connect("admin.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, username, role, department
        FROM admin
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    accounts = []
    for r in rows:
        accounts.append({
            "id": r[0],
            "username": r[1],
            "role": r[2],
            "department": r[3]
        })

    return jsonify({"success": True, "accounts": accounts})


@app.route("/api/admin/accounts", methods=["POST"])
def api_admin_accounts_create():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "").strip()
    department = (data.get("department") or "").strip()

    if not username or not password or not role:
        return jsonify({"success": False, "message": "Missing username/password/role"}), 400

    allowed_roles = {"admin", "guard", "dep_head"}
    if role not in allowed_roles:
        return jsonify({"success": False, "message": "Invalid role"}), 400

    # dep_head requires department
    if role == "dep_head" and not department:
        return jsonify({"success": False, "message": "Department is required for dep_head"}), 400

    # admin/guard should have NULL department
    if role in ("admin", "guard"):
        department = None

    try:
        conn = sqlite3.connect("admin.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO admin (username, password, role, department) VALUES (?, ?, ?, ?)",
            (username, password, role, department)
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()

        return jsonify({"success": True, "message": "Account created", "id": new_id})

    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "Username already exists"}), 409
    except Exception as e:
        print("api_admin_accounts_create error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route("/api/admin/accounts/<int:account_id>", methods=["DELETE"])
def api_admin_accounts_delete(account_id):
    # protect default system accounts (optional but recommended)
    protected_usernames = {"admin", "guard", "bsis_head", "crim_head", "bsa_head"}

    conn = sqlite3.connect("admin.db")
    cursor = conn.cursor()

    cursor.execute("SELECT username FROM admin WHERE id=?", (account_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Account not found"}), 404

    username = row[0]
    if username in protected_usernames:
        conn.close()
        return jsonify({"success": False, "message": "This account is protected"}), 403

    cursor.execute("DELETE FROM admin WHERE id=?", (account_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "Account deleted"})


#------------------Dept api----------------
@app.route('/api/dep/visitors', methods=['GET'])
def api_dep_visitors():
    department = request.args.get("department")
    if not department:
        return jsonify({"success": False, "message": "Missing department"}), 400

    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()

    rows = fetchall("""
        select
            id, name, reason, department, person_to_visit,
            visit_date, visit_time, email, valid_id, status,
            time_in, time_out, created_at, decision_note, decided_by, decided_at
        from public.visitors
        where department = %s
        order by visit_date desc, visit_time desc, id desc
    """, (department,))

    visitors = []
    for r in rows:
        visit_date = r["visit_date"]
        time_in = r["time_in"]

        derived_status = r["status"]

        if visit_date and visit_date < today_ph:
            if time_in is not None:
                derived_status = "Completed"
            else:
                derived_status = "No-show"

        visitors.append({
            "id": r["id"],
            "name": r["name"],
            "reason": r["reason"],
            "department": r["department"],
            "person_to_visit": r["person_to_visit"],
            "visit_date": str(visit_date) if visit_date else None,
            "visit_time": str(r["visit_time"]) if r["visit_time"] else None,
            "email": r["email"],
            "valid_id": r["valid_id"],
            "status": r["status"],
            "derived_status": derived_status,
            "time_in": r["time_in"].isoformat() if r["time_in"] else None,
            "time_out": r["time_out"].isoformat() if r["time_out"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "decision_note": r["decision_note"],
            "decided_by": r["decided_by"],
            "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
        })

    return jsonify({"success": True, "visitors": visitors})

# ---------------- GUARD API ----------------

@app.route('/api/guard/visitor/<int:visitor_id>', methods=['GET'])
def api_guard_get_visitor(visitor_id):
    row = fetchone("""
        select
            id, name, reason, person_to_visit, department,
            visit_date, visit_time, email, valid_id,
            time_in, time_out, status, created_at,
            decision_note, decided_by, decided_at
        from public.visitors
        where id = %s
    """, (visitor_id,))

    if not row:
        return jsonify({"success": False, "message": "Visitor not found"}), 404

    # Convert date/time/timestamptz safely to strings for Android
    def s(x):
        return x.isoformat() if hasattr(x, "isoformat") and x is not None else x

    return jsonify({
        "success": True,
        "visitor": {
            "id": row["id"],
            "name": row["name"],
            "reason": row["reason"],
            "person_to_visit": row["person_to_visit"],
            "department": row["department"],
            "visit_date": s(row["visit_date"]),       # date -> "YYYY-MM-DD"
            "visit_time": s(row["visit_time"]),       # time -> "HH:MM:SS"
            "email": row["email"],
            "valid_id": row["valid_id"],
            "time_in": s(row["time_in"]),             # timestamptz -> ISO string
            "time_out": s(row["time_out"]),
            "status": row["status"],
            "created_at": s(row["created_at"]),
            "decision_note": row["decision_note"],
            "decided_by": row["decided_by"],
            "decided_at": s(row["decided_at"]),
        }
    })

@app.route('/api/guard/scan/<int:visitor_id>', methods=['POST'])
def api_guard_scan(visitor_id):
    # 1) Read visitor
    row = fetchone("""
        select
            id, name, department, person_to_visit,
            visit_date, visit_time, status, time_in, time_out
        from public.visitors
        where id = %s
    """, (visitor_id,))

    if not row:
        return jsonify({"success": False, "message": "Visitor not found"}), 404

    vid = row["id"]
    name = row["name"]
    vdate = row["visit_date"]
    status = row["status"]
    time_in = row["time_in"]
    time_out = row["time_out"]

    # Status must be Approved
    if status != "Approved":
        return jsonify({"success": False, "message": f"Not allowed: status is {status}"}), 403

    # Appointment date must be today (Manila)
    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()
    if vdate != today_ph:
        return jsonify({
            "success": False,
            "message": f"Not allowed: appointment date is {vdate}"
        }), 403

    # Current actual scan time
    now_dt = datetime.now(ZoneInfo("Asia/Manila"))
    actual_time = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    # If no time_in yet → TIME IN
    if time_in is None:
        execute("""
            update public.visitors
            set time_in = %s
            where id = %s
        """, (now_dt, vid))

        brief = get_visitor_brief(vid)
        if brief:
            body_text = build_guard_scan_body(brief, "TIME_IN", actual_time)

            add_notification(
                target_role="admin",
                title="Visitor Arrived",
                body=body_text,
                type_="TIME_IN",
                visitor_id=vid
            )

            add_notification(
                target_role="dep_head",
                target_department=brief["department"],
                title="Visitor Arrived",
                body=body_text,
                type_="TIME_IN",
                visitor_id=vid
            )

        return jsonify({
            "success": True,
            "action": "TIME_IN",
            "message": f"Time-in recorded for {name}",
            "time": now_dt.isoformat()
        })

    # If time_in exists but no time_out yet → TIME OUT
    if time_in is not None and time_out is None:
        execute("""
            update public.visitors
            set time_out = %s
            where id = %s
        """, (now_dt, vid))

        brief = get_visitor_brief(vid)
        if brief:
            body_text = build_guard_scan_body(brief, "TIME_OUT", actual_time)

            add_notification(
                target_role="admin",
                title="Visitor Left",
                body=body_text,
                type_="TIME_OUT",
                visitor_id=vid
            )

            add_notification(
                target_role="dep_head",
                target_department=brief["department"],
                title="Visitor Left",
                body=body_text,
                type_="TIME_OUT",
                visitor_id=vid
            )

        return jsonify({
            "success": True,
            "action": "TIME_OUT",
            "message": f"Time-out recorded for {name}",
            "time": now_dt.isoformat()
        })

    # Already completed
    return jsonify({
        "success": False,
        "message": "Visitor already timed out (visit completed)."
    }), 409

@app.route("/api/guard/today", methods=["GET"])
def api_guard_today():
    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()

    rows = fetchall("""
        select
            id, name, reason, department, person_to_visit,
            visit_date, visit_time, email, status, time_in, time_out
        from public.visitors
        where status = 'Approved'
          and visit_date = %s
        order by visit_time asc
    """, (today_ph,))

    visitors = []
    for r in rows:
        visitors.append({
            "id": r["id"],
            "name": r["name"],
            "reason": r["reason"],
            "department": r["department"],
            "person_to_visit": r["person_to_visit"],
            "visit_date": str(r["visit_date"]),
            "visit_time": str(r["visit_time"]),
            "email": r["email"],
            "status": r["status"],
            "time_in": r["time_in"].isoformat() if r["time_in"] else None,
            "time_out": r["time_out"].isoformat() if r["time_out"] else None
        })

    return jsonify({
        "success": True,
        "visitors": visitors,
        "server_today_ph": today_ph.isoformat(),
        "count": len(visitors)
    })

@app.route("/api/notifications", methods=["GET"])
def api_get_notifications():
    role = request.args.get("role")
    department = request.args.get("department")

    if department is not None and department.strip() == "":
        department = None

    if not role:
        return jsonify({"success": False, "message": "Missing role"}), 400

    if role == "dep_head":
        if department:
            rows = fetchall("""
                select id, target_role, target_department, title, body, type, visitor_id, created_at, is_read
                from public.notifications
                where target_role = %s
                  and (target_department = %s or target_department is null)
                order by id desc
                limit 100
            """, (role, department))
        else:
            rows = fetchall("""
                select id, target_role, target_department, title, body, type, visitor_id, created_at, is_read
                from public.notifications
                where target_role = %s
                  and target_department is null
                order by id desc
                limit 100
            """, (role,))
    else:
        rows = fetchall("""
            select id, target_role, target_department, title, body, type, visitor_id, created_at, is_read
            from public.notifications
            where target_role = %s
            order by id desc
            limit 100
        """, (role,))

    notifications = []
    unread_count = 0

    for r in rows:
        is_read = bool(r["is_read"])
        if not is_read:
            unread_count += 1

        notifications.append({
            "id": r["id"],
            "target_role": r["target_role"],
            "target_department": r["target_department"],
            "title": r["title"],
            "body": r["body"],
            "type": r["type"],
            "visitor_id": r["visitor_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "is_read": 1 if is_read else 0
        })

    return jsonify({"success": True, "notifications": notifications, "unread_count": unread_count})

@app.route("/api/notifications/read/<int:notif_id>", methods=["POST"])
def api_mark_notification_read(notif_id):
    execute("update public.notifications set is_read = true where id = %s", (notif_id,))
    return jsonify({"success": True})

@app.route("/api/notifications/read_all", methods=["POST"])
def api_mark_all_read():
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    department = data.get("department")

    if not role:
        return jsonify({"success": False, "message": "Missing role"}), 400

    if role == "dep_head" and department:
        execute("""
            update public.notifications
            set is_read = true
            where target_role = %s
              and (target_department = %s or target_department is null)
        """, (role, department))
    else:
        execute("""
            update public.notifications
            set is_read = true
            where target_role = %s
        """, (role,))

    return jsonify({"success": True})


@app.get("/api/health/db")
def health_db():
    try:
        row = fetchone("select now() as now")
        return jsonify(success=True, now=str(row["now"]))
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500




@app.route('/api/premises-status', methods=['GET'])
def api_premises_status():
    role = request.args.get("role")
    department = request.args.get("department")

    if not role:
        return jsonify({"success": False, "message": "Missing role"}), 400

    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()

    params_inside = []
    params_left = [today_ph]

    where_inside = "where time_in is not null and time_out is null"
    where_left = "where time_out is not null and visit_date = %s"

    # dep_head sees only their own department
    if role == "dep_head":
        if not department:
            return jsonify({"success": False, "message": "Missing department"}), 400

        where_inside += " and department = %s"
        where_left += " and department = %s"
        params_inside.append(department)
        params_left.append(department)

    inside_rows = fetchall(f"""
        select
            id, name, department, person_to_visit,
            reason, visit_date, visit_time, time_in
        from public.visitors
        {where_inside}
        order by time_in desc
    """, tuple(params_inside))

    left_rows = fetchall(f"""
        select
            id, name, department, person_to_visit,
            reason, visit_date, visit_time, time_out
        from public.visitors
        {where_left}
        order by time_out desc
        limit 100
    """, tuple(params_left))

    inside = []
    for r in inside_rows:
        inside.append({
            "id": r["id"],
            "name": r["name"],
            "department": r["department"],
            "person_to_visit": r["person_to_visit"],
            "reason": r["reason"],
            "visit_date": str(r["visit_date"]) if r["visit_date"] else None,
            "visit_time": str(r["visit_time"]) if r["visit_time"] else None,
            "time_in": r["time_in"].isoformat() if r["time_in"] else None
        })

    left = []
    for r in left_rows:
        left.append({
            "id": r["id"],
            "name": r["name"],
            "department": r["department"],
            "person_to_visit": r["person_to_visit"],
            "reason": r["reason"],
            "visit_date": str(r["visit_date"]) if r["visit_date"] else None,
            "visit_time": str(r["visit_time"]) if r["visit_time"] else None,
            "time_out": r["time_out"].isoformat() if r["time_out"] else None
        })

    return jsonify({
        "success": True,
        "inside": inside,
        "left": left
    })

@app.route('/api/dep/send-message/<int:visitor_id>', methods=['POST'])
def api_dep_send_message(visitor_id):
    try:
        data = request.get_json(silent=True) or {}
        department = (data.get("department") or "").strip()
        message_text = (data.get("message") or "").strip()

        if not department:
            return jsonify({"success": False, "message": "Missing department"}), 400

        if not message_text:
            return jsonify({"success": False, "message": "Message is required"}), 400

        row = fetchone("""
            select id, name, email, department, time_in, time_out
            from public.visitors
            where id = %s
        """, (visitor_id,))

        if not row:
            return jsonify({"success": False, "message": "Visitor not found"}), 404

        # only same department
        if row["department"] != department:
            return jsonify({"success": False, "message": "Not allowed for this department"}), 403

        # only visitors currently inside premises
        if row["time_in"] is None or row["time_out"] is not None:
            return jsonify({"success": False, "message": "Visitor is not currently inside the premises"}), 400

        subject = "Message from Department Head - La Concepcion College"
        full_message = (
            f"Hello {row['name']},\n\n"
            f"{message_text}\n\n"
            f"This message was sent while you are currently inside the premises."
        )

        success, info = send_custom_visitor_email(
            to_email=row["email"],
            subject=subject,
            message_body=full_message
        )

        if not success:
            return jsonify({"success": False, "message": info}), 500

        return jsonify({"success": True, "message": "Email sent successfully"})

    except Exception as e:
        print("api_dep_send_message error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500



# Run Flask
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Use Render's port if available
    app.run(host="0.0.0.0", port=port)