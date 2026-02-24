import csv
from flask import Flask, render_template, request, redirect, session, send_from_directory, Response, jsonify
import os, random, sqlite3, qrcode, io, base64
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# ---------------- CONFIG ----------------
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


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
        ('about_paragraph1', 'La Concepcion College, Inc. (LCC) is founded in 1998...'),
        ('about_paragraph2', 'The LCC Online Appointment System was developed to make scheduling visits easier...'),
        ('how_intro', 'To ensure a smooth and organized visit, all visitors must schedule online.'),
        ('how_step1', 'Complete the required details on the appointment form.'),
        ('how_step2', 'After submitting, a unique QR code will be generated.'),
        ('how_step3', 'Your request will be reviewed by administration.'),
        ('how_step4', 'Present your QR code to security upon arrival.'),
        ('contact_phone', '(044) 762-36-60'),
        ('contact_phone_extra', '09276769921 – General Information'),
        ('contact_email', 'registrar@laconcepcioncollege.com'),
        ('contact_address', 'Kaypian Road, corner Quirino St, San Jose del Monte City, Bulacan, 3023')
    ]
    for section, content in default_content:
        cursor.execute("INSERT OR IGNORE INTO homepage_content (section, content) VALUES (?, ?)", (section, content))
    conn.commit()
    conn.close()


# Initialize databases
init_visitor_database()
init_admin_database()
init_homepage_database()


# ---------------- EMAIL SETTINGS ----------------
EMAIL_ADDRESS = os.environ.get("EMAIL_USER")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")


def send_email_otp(to_email, otp):
    """
    Send OTP email via SendGrid
    Returns: (success: bool, message: str)
    """
    print("📧 Attempting to send OTP email via SendGrid...")
    print(f"📧 From: {EMAIL_ADDRESS}")
    print(f"📧 To: {to_email}")

    # Check if credentials are set
    if not EMAIL_ADDRESS:
        error_msg = "EMAIL_USER environment variable is not set"
        print(f"❌ {error_msg}")
        return False, error_msg

    if not SENDGRID_API_KEY:
        error_msg = "SENDGRID_API_KEY environment variable is not set"
        print(f"❌ {error_msg}")
        return False, error_msg

    message = Mail(
        from_email=EMAIL_ADDRESS,
        to_emails=to_email,
        subject='Email Verification Code - La Concepcion College',
        html_content=f"""
        <html>
        <body>
            <p>Dear Visitor,</p>
            <p>Thank you for using the Gate Pass Appointment System.</p>
            <p>Your One-Time Verification Code (OTP) is: <b style="font-size: 24px; color: #0066cc;">{otp}</b></p>
            <p>Please enter this code on the Appointment website to verify your email address and continue your appointment request.</p>
            <p>This code will expire in 10 minutes.</p>
            <p>If you did not attempt to register, please ignore this message.</p>
            <br>
            <p>Best regards,<br>Gate Pass System Team<br>La Concepcion College</p>
        </body>
        </html>
        """
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"✅ Email sent successfully! Status code: {response.status_code}")
        return True, "Email sent successfully"
    except Exception as e:
        error_msg = f"SendGrid Error: {str(e)}"
        print(f"❌ {error_msg}")
        # Print more details for debugging
        if hasattr(e, 'body'):
            print(f"❌ Error body: {e.body}")
        return False, error_msg


def generate_otp():
    return str(random.randint(100000, 999999))


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
    return render_template('qr_form.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/accept_terms', methods=['POST'])
def accept_terms():
    session['accepted_terms'] = True
    return redirect('/appointment')


# Send OTP for verification
@app.route('/send_verification', methods=['POST'])
def send_verification():
    name = request.form['name']
    email = request.form['email']
    visit_date = request.form['visit_date']
    visit_time = request.form['visit_time']

    # ✅ Enforce date + time rules (Asia/Manila)
    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date()
    selected_date = datetime.strptime(visit_date, "%Y-%m-%d").date()

    # Date must be tomorrow onwards
    if selected_date <= today_ph:
        return render_template(
            "Error.html",
            message="⚠️ Same-day appointments are not allowed. Please choose tomorrow or later."
        )

    # Time must be 09:00–16:00
    try:
        selected_time = datetime.strptime(visit_time, "%H:%M").time()
    except ValueError:
        return render_template("Error.html", message="⚠️ Invalid time format.")

    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("16:00", "%H:%M").time()

    # Decide whether 4:00 PM is allowed:
    # - If you want 4:00 PM allowed, keep `>` as below.
    # - If you want only up to 3:59 PM, change to `>=`.
    if selected_time < start_time or selected_time > end_time:
        return render_template(
            "Error.html",
            message="⚠️ Visiting hours are only from 9:00 AM to 4:00 PM. Please select a valid time."
        )

    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM visitors WHERE name=? AND visit_date=? AND visit_time=?",
                   (name, visit_date, visit_time))
    if cursor.fetchone():
        conn.close()
        return render_template('Error.html', message="⚠️ You already have an appointment for this date and time.")

    cursor.execute("SELECT is_verified FROM visitors WHERE email=?", (email,))
    verified_record = cursor.fetchone()
    conn.close()

    session['visitor_info'] = {
        'name': name,
        'reason': request.form['reason'],
        'person_to_visit': request.form['person_to_visit'],
        'department': request.form['department'],  # <-- new
        'visit_date': visit_date,
        'visit_time': visit_time,
        'email': email
    }

    file = request.files.get('valid_id')
    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        session['valid_id_filename'] = filename
    else:
        session['valid_id_filename'] = None

    if verified_record and verified_record[0] == 1:
        session['verified_email'] = email
        conn = sqlite3.connect('visitors.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO visitors (name, reason, person_to_visit, department, visit_date, visit_time, email, valid_id, created_at, is_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            name,
            session['visitor_info']['reason'],
            session['visitor_info']['person_to_visit'],
            session['visitor_info']['department'],
            visit_date,
            visit_time,
            email,
            session.get('valid_id_filename'),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            1
        ))
        conn.commit()
        conn.close()
        return redirect('/generate_qr_form')

    # Generate and send OTP
    otp = generate_otp()
    session['otp'] = otp
    session['otp_timestamp'] = datetime.now().timestamp()  # For expiration checking

    # Send email with proper error handling
    success, message = send_email_otp(email, otp)

    if success:
        return render_template('verify_email.html', email=email)
    else:
        # Return error page with detailed message
        error_message = f"❌ Failed to send verification email. {message}"
        print(error_message)
        return render_template('Error.html', message=error_message)


# Verify OTP
@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    entered_otp = request.form['otp']
    stored_otp = session.get('otp')
    otp_timestamp = session.get('otp_timestamp')

    # Check if OTP exists
    if not stored_otp:
        return render_template('Error.html', message="❌ OTP session expired. Please request a new code.")

    # Check if OTP is expired (10 minutes)
    if otp_timestamp:
        elapsed_time = datetime.now().timestamp() - otp_timestamp
        if elapsed_time > 600:
            return render_template('Error.html', message="❌ OTP has expired. Please request a new code.")

    if entered_otp == stored_otp:

        visitor_info = session.get('visitor_info')
        filename = session.get('valid_id_filename')

        conn = sqlite3.connect('visitors.db')
        cursor = conn.cursor()

        # Mark email verified (optional but fine)
        cursor.execute("UPDATE visitors SET is_verified=1 WHERE email=?", (visitor_info['email'],))

        # Insert visitor
        cursor.execute('''
            INSERT INTO visitors 
            (name, reason, person_to_visit, department, visit_date, visit_time, email, valid_id, created_at, is_verified, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            visitor_info['name'],
            visitor_info['reason'],
            visitor_info['person_to_visit'],
            visitor_info['department'],
            visitor_info['visit_date'],
            visitor_info['visit_time'],
            visitor_info['email'],
            filename,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            1,
            'Pending'
        ))

        # ✅ NOW cursor exists and INSERT is done
        visitor_id = cursor.lastrowid
        session["visitor_id"] = visitor_id

        conn.commit()
        conn.close()

        session['verified_email'] = visitor_info['email']

        # Clear OTP
        session.pop('otp', None)
        session.pop('otp_timestamp', None)

        return render_template('pending_approval.html')

    else:
        return render_template('Error.html', message="❌ Invalid OTP. Please try again or request a new code.")


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
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, reason, person_to_visit, department, visit_date, visit_time, email, valid_id FROM visitors WHERE id=?", (visitor_id,))
    visitor = cursor.fetchone()
    conn.close()

    if not visitor:
        return "❌ Visitor not found", 404

    visitor_info = {
        'name': visitor[0],
        'reason': visitor[1],
        'person_to_visit': visitor[2],
        'department': visitor[3],
        'visit_date': visitor[4],
        'visit_time': visitor[5],
        'email': visitor[6]
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
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    if filter_type == 'week':
        start_date = datetime.now() - timedelta(days=7)
        cursor.execute("SELECT * FROM visitors WHERE created_at >= ? ORDER BY id DESC",
                       (start_date.strftime('%Y-%m-%d %H:%M:%S'),))
    elif filter_type == 'month':
        start_date = datetime.now() - timedelta(days=30)
        cursor.execute("SELECT * FROM visitors WHERE created_at >= ? ORDER BY id DESC",
                       (start_date.strftime('%Y-%m-%d %H:%M:%S'),))
    elif filter_type == 'year':
        start_date = datetime.now() - timedelta(days=365)
        cursor.execute("SELECT * FROM visitors WHERE created_at >= ? ORDER BY id DESC",
                       (start_date.strftime('%Y-%m-%d %H:%M:%S'),))
    else:
        cursor.execute("SELECT * FROM visitors ORDER BY id DESC")

    visitors = cursor.fetchall()
    conn.close()
    return render_template('admin_dashboard.html', visitors=visitors, filter_type=filter_type)

@app.route('/admin/approve/<int:visitor_id>')
def approve_visitor(visitor_id):
    if 'admin' not in session:
        return redirect('/admin/login')

    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("UPDATE visitors SET status='Approved' WHERE id=?", (visitor_id,))
    conn.commit()

    cursor.execute("SELECT email FROM visitors WHERE id=?", (visitor_id,))
    email = cursor.fetchone()[0]
    conn.close()

    # Send approval email with QR link
    qr_link = f"https://emailandmobileapp.onrender.com/generate_qr/{visitor_id}"

    message = Mail(
        from_email=EMAIL_ADDRESS,
        to_emails=email,
        subject="Visit Approved - La Concepcion College",
        html_content=f"""
        <p>Your visit has been approved.</p>
        <p>Please save your QR code here:</p>
        <a href="{qr_link}">{qr_link}</a>
        """
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        print("Email sending failed:", e)

    return redirect('/admin/dashboard')

@app.route('/admin/decline/<int:visitor_id>')
def decline_visitor(visitor_id):
    if 'admin' not in session:
        return redirect('/admin/login')

    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("UPDATE visitors SET status='Declined' WHERE id=?", (visitor_id,))
    conn.commit()

    cursor.execute("SELECT email FROM visitors WHERE id=?", (visitor_id,))
    email = cursor.fetchone()[0]
    conn.close()

    message = Mail(
        from_email=EMAIL_ADDRESS,
        to_emails=email,
        subject="Visit Declined",
        html_content="<p>We are sorry, your visit request was declined.</p>"
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        print("Email sending failed:", e)

    return redirect('/admin/dashboard')


# Download CSV
@app.route('/admin/download_csv')
def download_csv():
    if 'admin' not in session:
        return redirect('/admin/login')

    filter_type = request.args.get('filter')
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()
    if filter_type == 'week':
        start_date = datetime.now() - timedelta(days=7)
        cursor.execute("SELECT * FROM visitors WHERE created_at >= ? ORDER BY id DESC",
                       (start_date.strftime('%Y-%m-%d %H:%M:%S'),))
    elif filter_type == 'month':
        start_date = datetime.now() - timedelta(days=30)
        cursor.execute("SELECT * FROM visitors WHERE created_at >= ? ORDER BY id DESC",
                       (start_date.strftime('%Y-%m-%d %H:%M:%S'),))
    elif filter_type == 'year':
        start_date = datetime.now() - timedelta(days=365)
        cursor.execute("SELECT * FROM visitors WHERE created_at >= ? ORDER BY id DESC",
                       (start_date.strftime('%Y-%m-%d %H:%M:%S'),))
    else:
        cursor.execute("SELECT * FROM visitors ORDER BY id DESC")
    visitors = cursor.fetchall()
    conn.close()

    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(
            ['ID', 'Name', 'Reason', 'Person to Visit', 'Date', 'Time', 'Email', 'Valid ID', 'Time In', 'Time Out',
             'Created At'])
        yield data.getvalue()
        data.seek(0)
        data.truncate(0)
        for row in visitors:
            writer.writerow([row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10]])
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

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Missing username or password"
        }), 400

    conn = sqlite3.connect('admin.db')
    cursor = conn.cursor()

    # role + department
    cursor.execute(
        "SELECT role, department FROM admin WHERE username=? AND password=?",
        (username, password)
    )
    row = cursor.fetchone()
    conn.close()

    if row:
        role, department = row[0], row[1]
        return jsonify({
            "success": True,
            "role": role,
            "department": department  # will be null for admin/guard
        })

    return jsonify({
        "success": False,
        "message": "Invalid credentials"
    }), 401


@app.route('/api/admin/visitors', methods=['GET'])
def api_admin_visitors():
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, reason, department, person_to_visit, visit_date, visit_time, email, status, created_at
        FROM visitors
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    visitors = []
    for r in rows:
        visitors.append({
            "id": r[0],
            "name": r[1],
            "reason": r[2],
            "department": r[3],
            "person_to_visit": r[4],
            "visit_date": r[5],
            "visit_time": r[6],
            "email": r[7],
            "status": r[8],
            "created_at": r[9],
        })

    return jsonify(visitors)

@app.route('/api/admin/approve/<int:visitor_id>', methods=['POST'])
def api_admin_approve(visitor_id):
    try:
        conn = sqlite3.connect('visitors.db')
        cursor = conn.cursor()

        cursor.execute("UPDATE visitors SET status='Approved' WHERE id=?", (visitor_id,))
        conn.commit()

        cursor.execute("SELECT email FROM visitors WHERE id=?", (visitor_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({"success": False, "message": "Visitor not found"}), 404

        email = row[0]

        # link that shows visitor QR code (you said this already works)
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

        return jsonify({"success": True, "message": "Approved and email sent"})

    except Exception as e:
        print("api_admin_approve error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/admin/decline/<int:visitor_id>', methods=['POST'])
def api_admin_decline(visitor_id):
    try:
        conn = sqlite3.connect('visitors.db')
        cursor = conn.cursor()

        cursor.execute("UPDATE visitors SET status='Declined' WHERE id=?", (visitor_id,))
        conn.commit()

        cursor.execute("SELECT email FROM visitors WHERE id=?", (visitor_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify({"success": False, "message": "Visitor not found"}), 404

        email = row[0]

        message = Mail(
            from_email=EMAIL_ADDRESS,
            to_emails=email,
            subject="Visit Declined - La Concepcion College",
            html_content="<p>We are sorry, your visit request was <b>declined</b>.</p>"
        )

        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
        except Exception as e:
            print("Decline email failed:", e)

        return jsonify({"success": True, "message": "Declined and email sent"})

    except Exception as e:
        print("api_admin_decline error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500


@app.route('/api/dep/visitors', methods=['GET'])
def api_dep_visitors():
    department = request.args.get("department")
    if not department:
        return jsonify({"success": False, "message": "Missing department"}), 400

    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, reason, department, person_to_visit, visit_date, visit_time, email, status, created_at
        FROM visitors
        WHERE department = ?
        ORDER BY id DESC
    """, (department,))
    rows = cursor.fetchall()
    conn.close()

    visitors = []
    for r in rows:
        visitors.append({
            "id": r[0],
            "name": r[1],
            "reason": r[2],
            "department": r[3],
            "person_to_visit": r[4],
            "visit_date": r[5],
            "visit_time": r[6],
            "email": r[7],
            "status": r[8],
            "created_at": r[9],
        })

    return jsonify(visitors)

# ---------------- GUARD API ----------------

@app.route('/api/guard/visitor/<int:visitor_id>', methods=['GET'])
def api_guard_get_visitor(visitor_id):
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, reason, person_to_visit, department,
               visit_date, visit_time, email, valid_id,
               time_in, time_out, status, created_at
        FROM visitors
        WHERE id=?
    """, (visitor_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "message": "Visitor not found"}), 404

    return jsonify({
        "success": True,
        "visitor": {
            "id": row[0],
            "name": row[1],
            "reason": row[2],
            "person_to_visit": row[3],
            "department": row[4],
            "visit_date": row[5],
            "visit_time": row[6],
            "email": row[7],
            "valid_id": row[8],
            "time_in": row[9],
            "time_out": row[10],
            "status": row[11],
            "created_at": row[12],
        }
    })
@app.route('/api/guard/scan/<int:visitor_id>', methods=['POST'])
def api_guard_scan(visitor_id):
    conn = sqlite3.connect('visitors.db')
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, department, person_to_visit,
               visit_date, visit_time, status, time_in, time_out
        FROM visitors WHERE id=?
    """, (visitor_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"success": False, "message": "Visitor not found"}), 404

    (vid, name, dept, person, vdate, vtime, status, time_in, time_out) = row

    # ✅ Status must be Approved
    if status != "Approved":
        conn.close()
        return jsonify({"success": False, "message": f"Not allowed: status is {status}"}), 403

    # ✅ Expiration check: compare visit_date to today (Manila)
    today = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d")
    if vdate != today:
        conn.close()
        return jsonify({"success": False, "message": f"Not allowed: appointment date is {vdate}"}), 403

    now_str = datetime.now(ZoneInfo("Asia/Manila")).strftime("%Y-%m-%d %H:%M:%S")

    # If no time_in yet → auto TIME IN
    if not time_in:
        cursor.execute("UPDATE visitors SET time_in=? WHERE id=?", (now_str, vid))
        conn.commit()
        conn.close()
        return jsonify({
            "success": True,
            "action": "TIME_IN",
            "message": f"Time-in recorded for {name}",
            "time": now_str
        })

    # If time_in exists but no time_out yet → auto TIME OUT
    if time_in and not time_out:
        cursor.execute("UPDATE visitors SET time_out=? WHERE id=?", (now_str, vid))
        conn.commit()
        conn.close()
        return jsonify({
            "success": True,
            "action": "TIME_OUT",
            "message": f"Time-out recorded for {name}",
            "time": now_str
        })

    # If both exist → already completed
    conn.close()
    return jsonify({
        "success": False,
        "message": "Visitor already timed out (visit completed)."
    }), 409

@app.route("/api/guard/today", methods=["GET"])
def api_guard_today():
    today_ph = datetime.now(ZoneInfo("Asia/Manila")).date().isoformat()  # "YYYY-MM-DD"

    conn = sqlite3.connect("visitors.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, reason, department, person_to_visit, visit_date, visit_time,
               email, status, time_in, time_out
        FROM visitors
        WHERE status = 'Approved'
          AND visit_date = ?
        ORDER BY visit_time ASC
    """, (today_ph,))

    rows = cursor.fetchall()
    conn.close()

    visitors = []
    for r in rows:
        visitors.append({
            "id": r[0],
            "name": r[1],
            "reason": r[2],
            "department": r[3],
            "person_to_visit": r[4],
            "visit_date": r[5],
            "visit_time": r[6],
            "email": r[7],
            "status": r[8],
            "time_in": r[9],
            "time_out": r[10]
        })

    return jsonify({
        "success": True,
        "visitors": visitors,
        "server_today_ph": today_ph,   # helpful debug
        "count": len(visitors)
    })


# Run Flask
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Use Render's port if available
    app.run(host="0.0.0.0", port=port)