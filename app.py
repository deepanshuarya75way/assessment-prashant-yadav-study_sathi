from flask import Flask, render_template, request, redirect, url_for, session, flash , jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, uuid
from concurrent.futures import ThreadPoolExecutor 

app = Flask(__name__)
app.secret_key = 'study-sathi-secret-key-change-in-production'

DB = 'study_sathi.db'

#BACKGROUNG PROCESSING

executor = ThreadPoolExecutor(max_workers=2)

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT,
            owner_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS memberships (
            user_id TEXT,
            group_id TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, group_id)
        );
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            status TEXT DEFAULT 'processing',
            extracted_text TEXT,
            thumbnail_filename TEXT,
            processsing_error TEXT,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    message TEXT NOT NULL,
    sent_at TEXT DEFAULT CURRENT_TIMESTAMP
);
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def extract_pdf_text(file_bytes):
    from pypdf import PdfReader
    pdf = pdfReader(io.BytesIO(file_bytes))
text = [] 

for page in pdf.pages:
    text.append(page.extract_text() or "")
return"\n".join (text)
def generate_pdf_thumbnail(file_bytes):
    import fitz
    pdf = fitz.open(
        stream = file_bytes,
        filetype = "pdf"
    )

if pdf.page_count == 0:
    pdf.close()
    return none

    page = pdf.load_page(0)

pix = page.get_pixmap(
matrix+fitz.matrix(1,2,1,2),
alpha=false
)
image=pix.tobytes("png")
pdf.close()
return image

def process_note(note_id):

    try:
        import boto3
        conn=get_db()
        note=conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id, )
           ).fetchone()
        conn.close()
        
        if not note:
        return

    s3 = boto3.client(
        's3',
        region_name=os.environ.get('AWS_REGION'),
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key = environ.get('AWS_SECRET_ACCESS_KEY')
    )
bucket=os.environ.get('s3_BUCKET')
file_object = io.BytesID()

s3.download_fileobj(
    bucket,
    note['filename'],
file_object
)

file_bytes=file_object.getvalue()
extracted_text=""
thumbnail_filename = None

if note['original_name'].lower().endwith('.pdf'):

    extracted_text=extract_pdf_text(
        file_bytes
    )
thumbnial=generate_pdf_thumbnail(
    file_bytes
)

if thumbnial:
    thumbnail_filename = (
        f"thumbnails/[note_id].png"
    )

    s3.upload_fileobj(
        io.BytesIO(thumbnial),
        bucket,
        thumbnail_filename,
        ExtraArgs={
            "contentype": "image/png"
        }
    )

elif note['orignal_name'].lower().endwith('.txt'):
    extracted_text=file_bytes.decode(
        'utf-8',
        errors="ignore"
    )

    conn=get_dd()
conn.execute(
    """
    UPDATE notes
    SET
    status=?
    extracted_text=?
    thumbnial_filename=?
    processing_error=NULL
    WHERE id =?
    """
    (
        'completed',
        extracted_text,
        thumbnail_filename,
        note_id

    )
)
conn.commit()
conn.close()
print( f"Note{note_id}processing completed")
except Exception as e :
print( f"Note processing failed: {e}")
conn=get_db()
conn.execute(
    """
     UPDATE notes
    SET
    status=?
    processing_error=?
    WHERE id =?
    """,
    (
        'failed',
        str(e),
        note_id
)
)
conn.commit()
conn.close()



def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        conn = get_db()
        try:
            conn.execute('INSERT INTO users (id, name, email, password) VALUES (?, ?, ?, ?)',
                (str(uuid.uuid4()), name, email, generate_password_hash(password)))
            conn.commit()
            flash('Account created! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'error')
        finally:
            conn.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    my_groups = conn.execute('''
        SELECT g.* FROM groups g
        JOIN memberships m ON g.id = m.group_id
        WHERE m.user_id = ?
    ''', (session['user_id'],)).fetchall()
    all_groups = conn.execute('''
        SELECT g.*, u.name as owner_name,
        (SELECT COUNT(*) FROM memberships WHERE group_id = g.id) as member_count
        FROM groups g JOIN users u ON g.owner_id = u.id
    ''').fetchall()
    conn.close()
    return render_template('dashboard.html', my_groups=my_groups, all_groups=all_groups)

@app.route('/group/create', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        group_id = str(uuid.uuid4())
        conn = get_db()
        conn.execute('INSERT INTO groups (id, name, subject, description, owner_id) VALUES (?, ?, ?, ?, ?)',
            (group_id, request.form['name'], request.form['subject'],
             request.form['description'], session['user_id']))
        conn.execute('INSERT INTO memberships (user_id, group_id) VALUES (?, ?)',
            (session['user_id'], group_id))
        conn.commit()
        conn.close()
        flash('Group created!', 'success')
        return redirect(url_for('group_detail', group_id=group_id))
    return render_template('create_group.html')

@app.route('/group/<group_id>')
def group_detail(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ?', (group_id,)).fetchone()
    members = conn.execute('''
        SELECT u.name, u.email FROM users u
        JOIN memberships m ON u.id = m.user_id
        WHERE m.group_id = ?
    ''', (group_id,)).fetchall()
    notes = conn.execute('''
        SELECT n.*, u.name as uploader FROM notes n
        JOIN users u ON n.user_id = u.id
        WHERE n.group_id = ?
        ORDER BY n.uploaded_at DESC
    ''', (group_id,)).fetchall()
    messages = conn.execute('''SELECT m.*, u.name as sender FROM messages m JOIN users u ON m.user_id = u.id WHERE m.group_id = ? ORDER BY m.sent_at ASC''', (group_id,)).fetchall()
    is_member = conn.execute('SELECT 1 FROM memberships WHERE user_id=? AND group_id=?',
        (session['user_id'], group_id)).fetchone()
    conn.close()
    return render_template('group.html', group=group, members=members, notes=notes, is_member=is_member, messages=messages)
@app.route('/group/<group_id>/join')
def join_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    try:
        conn.execute('INSERT INTO memberships (user_id, group_id) VALUES (?, ?)',
            (session['user_id'], group_id))
        conn.commit()
        flash('Joined group!', 'success')
    except:
        flash('Already a member.', 'info')
    finally:
        conn.close()
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/group/<group_id>/upload', methods=['POST'])
def upload_note(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    file = request.files.get('file')
    if file and file.filename:
        flash('select a file', 'error')
        return redirect (url_for('group_detail',
        group_id=group_id))
       try:
        import boto3
        note_id = str(uuid.uuid4())
        filename = f"{note_id}_{file.filename}"
        s3boto3.client('s3',
            region_name=os.environ.get('AWS_REGION'),
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
        )
        s3.upload_fileobj(file, os.environ.get('S3_BUCKET'), filename)
        s3_url = f'https://d2ct19a2czyq1f.cloudfront.net/{filename}'
        conn = get_db()
        conn.execute('INSERT INTO notes (id, group_id, user_id, filename, original_name) VALUES (?,?,?,?,?)',
            (note_id, group_id, session['user_id'], filename, file.filename))
        conn.commit()
        conn.close()
        flash('Note uploaded to S3!', 'success')
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/note/<note_id>/status')
def note_status(note_id):
    db = get_db()
    note = db.execute(
        "SELECT id, orignal_name, status, thumbnial_filename FROM notes WHERE id=?",
     (note_id,)
    ).fetchone()
    db.close( )
    return jsonify(dict(note)) if note else jsonify(errors='Not Found'),404

@app.route('/group/<group_id>/delete_note/<note_id>')
def delete_note(group_id, note_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    import boto3
    conn = get_db()
    note = conn.execute('SELECT * FROM notes WHERE id = ? AND user_id = ?',
        (note_id, session['user_id'])).fetchone()
    if note:
        s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION'))
        s3.delete_object(Bucket=os.environ.get('S3_BUCKET'), Key=note['filename'])
        conn.execute('DELETE FROM notes WHERE id = ?', (note_id,))
        conn.commit()
        flash('Note deleted!', 'success')
    conn.close()
    return redirect(url_for('group_detail', group_id=group_id))

@app.route('/search')
def search():
    query = request.args.get('q', '')
    conn = get_db()
    groups = conn.execute('''
        SELECT g.*, u.name as owner_name,
        (SELECT COUNT(*) FROM memberships WHERE group_id = g.id) as member_count
        FROM groups g JOIN users u ON g.owner_id = u.id
        WHERE g.name LIKE ? OR g.subject LIKE ?
    ''', (f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    return render_template('search.html', groups=groups, query=query)
@app.route('/group/<group_id>/delete')
def delete_group(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    group = conn.execute('SELECT * FROM groups WHERE id = ? AND owner_id = ?',
        (group_id, session['user_id'])).fetchone()
    if group:
        conn.execute('DELETE FROM notes WHERE group_id = ?', (group_id,))
        conn.execute('DELETE FROM memberships WHERE group_id = ?', (group_id,))
        conn.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        conn.commit()
        flash('Group deleted!', 'success')
    else:
        flash('You are not the owner!', 'error')
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/group/<group_id>/chat', methods=['POST'])
def send_message(group_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    message = request.form.get('message', '').strip()
    if message:
        conn = get_db()
        conn.execute('INSERT INTO messages (id, group_id, user_id, message) VALUES (?,?,?,?)',
            (str(uuid.uuid4()), group_id, session['user_id'], message))
        conn.commit()
        conn.close()
    return redirect(url_for('group_detail', group_id=group_id))
if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
