import json
import os
import random
import time
import threading
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_123'

socketio = SocketIO(app, async_mode='threading')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'database.json')
db_lock = threading.Lock()

price_history = {'gold': [], 'silver': []}
history_lock = threading.Lock()

def get_db():
    if not os.path.exists(DB_FILE):
        default_data = {"users": [], "gold_rate": 16000.00, "silver_rate": 268.00}
        with open(DB_FILE, 'w') as f:
            json.dump(default_data, f, indent=4)
        return default_data
    
    with db_lock:
        with open(DB_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {"users": [], "gold_rate": 16000.00}

def save_db(data):
    with db_lock:
        with open(DB_FILE, 'w') as f:
            json.dump(data, f, indent=4)

def background_thread():
    while True:
        with db_lock:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    try:
                        db = json.load(f)
                    except:
                        db = {"users": [], "gold_rate": 16000.00, "silver_rate": 268.00}
            else:
                db = {"users": [], "gold_rate": 16000.00, "silver_rate": 268.00}

            base_price = db.get('gold_rate', 16000.00)
            change = random.uniform(-50, 50)
            new_price = round(base_price + change, 2)
            new_price = max(15500.00, min(17000.00, new_price))
            db['gold_rate'] = new_price
            
            base_silver = db.get('silver_rate', 268.00)
            change_s = random.uniform(-3, 3)
            new_silver = round(base_silver + change_s, 2)
            new_silver = max(190.00, min(300.00, new_silver))
            db['silver_rate'] = new_silver
            
            with open(DB_FILE, 'w') as f:
                json.dump(db, f, indent=4)
        
        with history_lock:
            ts = datetime.now().strftime('%H:%M')
            price_history['gold'].append({'time': ts, 'price': new_price})
            price_history['silver'].append({'time': ts, 'price': new_silver})
            if len(price_history['gold']) > 1440:
                price_history['gold'].pop(0)
            if len(price_history['silver']) > 1440:
                price_history['silver'].pop(0)
        
        socketio.emit('live_price', {'metal': 'gold', 'price': new_price}, namespace='/gold')
        socketio.emit('live_price', {'metal': 'silver', 'price': new_silver}, namespace='/gold')
        time.sleep(2)

thread = threading.Thread(target=background_thread)
thread.daemon = True
thread.start()

@app.route('/')
def index():
    if 'user_phone' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form.get('phone')
        name = request.form.get('name')
        
        db = get_db()
        user = next((u for u in db['users'] if u['phone'] == phone), None)

        if user:
            session['user_phone'] = phone
            session['temp_otp'] = '123456'
            return redirect(url_for('verify'))
        
        if not name:
            flash('Phone number not registered. Please enter your name to register.')
            return render_template('login.html', show_name_field=True)
        
        new_user = {
            "phone": phone,
            "name": name,
            "email": f"{phone}@user.com",
            "gold_balance": 0.0000,
            "silver_balance": 0.0000,
            "wallet_balance": 10000.00,
            "bank_details": {},
            "transactions": []
        }
        db['users'].append(new_user)
        save_db(db)
        
        session['user_phone'] = phone
        session['temp_otp'] = '123456'
        return redirect(url_for('verify'))

    return render_template('login.html', show_name_field=False)

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    # Ensure a temporary OTP exists in session (development fallback)
    if 'temp_otp' not in session:
        session['temp_otp'] = '123456'

    if request.method == 'POST':
        otp_input = (request.form.get('otp') or '').strip()
        temp_otp = str(session.get('temp_otp', '123456')).strip()
        if otp_input and otp_input == temp_otp:
            session.pop('temp_otp', None)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid OTP. Try 123456')

    return render_template('verify.html', phone=session.get('user_phone'))

@app.route('/dashboard')
def dashboard():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    
    if not user:
        session.clear()
        return redirect(url_for('login'))
        
    return render_template('dashboard.html', user=user)

@app.route('/get_data')
def get_data():
    if 'user_phone' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "wallet": user['wallet_balance'],
        "gold": user.get('gold_balance', 0.0),
        "silver": user.get('silver_balance', 0.0),
        "price_gold": db.get('gold_rate', 0.0),
        "price_silver": db.get('silver_rate', None),
        "transactions": user.get('transactions', [])[-20:]
    })


@app.route('/get_rate')
def get_rate():
    metal = request.args.get('metal', 'gold').lower()
    db = get_db()
    if metal == 'silver':
        rate = db.get('silver_rate', db.get('gold_rate', 16000.00))
    else:
        rate = db.get('gold_rate', 16000.00)
    return jsonify({"rate": rate})


@app.route('/save_manually')
def save_manually():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    metal = request.args.get('metal', 'gold')
    return render_template('save_manually.html', metal=metal)


@app.route('/sell_manually')
def sell_manually():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    metal = request.args.get('metal', 'gold')
    return render_template('sell_manually.html', metal=metal)


@app.route('/get_price_history')
def get_price_history():
    metal = request.args.get('metal', 'gold').lower()
    with history_lock:
        data = price_history.get(metal, [])
    return jsonify({"history": data})


@app.route('/live_price')
def live_price_page():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    metal = request.args.get('metal', 'gold')
    db = get_db()
    if metal == 'silver':
        rate = db.get('silver_rate', db.get('gold_rate', 268.00))
    else:
        rate = db.get('gold_rate', 16000.00)
    return render_template('live_price.html', metal=metal, rate=rate)

@app.route('/sell', methods=['POST'])
def sell_gold():
    data = request.json
    if not data or 'grams' not in data:
        return jsonify({"success": False, "msg": "Invalid data"}), 400

    try:
        grams = float(data.get('grams'))
    except ValueError:
        return jsonify({"success": False, "msg": "Invalid number"}), 400
    
    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    metal = data.get('metal', 'gold')
    rate = db.get('gold_rate', 16000.00)
    if metal == 'silver':
        rate = db.get('silver_rate', rate)

    bal_field = 'gold_balance' if metal == 'gold' else 'silver_balance'
    if user.get(bal_field, 0.0) >= grams:
        amount = grams * rate
        user[bal_field] = user.get(bal_field, 0.0) - grams
        user['wallet_balance'] += amount
        
        tx = {
            "type": "SELL",
            "amount": amount,
            "grams": grams,
            "rate": rate,
            "metal": metal,
            "date": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        user['transactions'].append(tx)
        save_db(db)
        return jsonify({"success": True, "msg": f"Sold {grams}g {metal} for ₹{amount:.2f}"})
    else:
        return jsonify({"success": False, "msg": f"Not enough {metal} balance"}), 400

@app.route('/payment/<amount>')
def payment(amount):
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    
    try:
        amount_value = float(amount)
    except ValueError:
        return "Invalid Amount", 400

    return render_template('payment.html', amount=amount_value)

@app.route('/process_payment', methods=['POST'])
def process_payment():
    # Validate session
    if 'user_phone' not in session:
        return jsonify({"success": False, "msg": "Unauthorized - login required"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "msg": "Invalid JSON payload"}), 400

    method = data.get('method')
    metal = data.get('metal', 'gold')

    # Validate amount
    try:
        amount = float(data.get('amount'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "msg": "Invalid amount"}), 400

    if amount <= 0:
        return jsonify({"success": False, "msg": "Amount must be positive"}), 400

    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    if not user:
        return jsonify({"success": False, "msg": "User not found"}), 404

    rate = db.get('gold_rate', 16000.00)
    if metal == 'silver':
        rate = db.get('silver_rate', rate)

    # Wallet payment
    if method == 'wallet':
        if user.get('wallet_balance', 0.0) < amount:
            return jsonify({"success": False, "msg": "Insufficient Wallet Balance"}), 400

        user['wallet_balance'] = user.get('wallet_balance', 0.0) - amount
        qty_bought = amount / rate
        if metal == 'gold':
            user['gold_balance'] = user.get('gold_balance', 0.0) + qty_bought
        else:
            user['silver_balance'] = user.get('silver_balance', 0.0) + qty_bought

        tx = {
            "type": "BUY (Wallet)",
            "amount": amount,
            "grams": qty_bought,
            "rate": rate,
            "metal": metal,
            "date": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        user.setdefault('transactions', []).append(tx)
        save_db(db)
        return jsonify({"success": True})

    # Card payment (simulated)
    elif method == 'card':
        qty_bought = amount / rate
        if metal == 'gold':
            user['gold_balance'] = user.get('gold_balance', 0.0) + qty_bought
        else:
            user['silver_balance'] = user.get('silver_balance', 0.0) + qty_bought

        tx = {
            "type": "BUY (Card)",
            "amount": amount,
            "grams": qty_bought,
            "rate": rate,
            "metal": metal,
            "date": datetime.now().strftime("%d %b %Y, %I:%M %p")
        }
        user.setdefault('transactions', []).append(tx)
        save_db(db)
        return jsonify({"success": True})

    return jsonify({"success": False, "msg": "Invalid payment method"}), 400

@app.route('/profile')
def profile():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    if not user:
        session.clear()
        return redirect(url_for('login'))
    return render_template('profile.html', user=user)


@app.route('/profile/update', methods=['POST'])
def profile_update():
    if 'user_phone' not in session:
        return redirect(url_for('login'))
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip()
    if not name:
        flash('Name cannot be empty', 'error')
        return redirect(url_for('profile'))
    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    if not user:
        session.clear()
        return redirect(url_for('login'))
    user['name'] = name
    if email:
        user['email'] = email
    save_db(db)
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('profile'))


@app.route('/profile/add_wallet', methods=['POST'])
def profile_add_wallet():
    if 'user_phone' not in session:
        return jsonify({"success": False, "msg": "Unauthorized"}), 401
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "msg": "Invalid request"}), 400
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "msg": "Invalid amount"}), 400
    if amount <= 0:
        return jsonify({"success": False, "msg": "Amount must be positive"}), 400
    db = get_db()
    user = next((u for u in db['users'] if u['phone'] == session['user_phone']), None)
    if not user:
        return jsonify({"success": False, "msg": "User not found"}), 404
    user['wallet_balance'] = user.get('wallet_balance', 0.0) + amount
    save_db(db)
    return jsonify({"success": True, "new_balance": user['wallet_balance']})


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)