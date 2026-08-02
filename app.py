import os
import re
import sqlite3
import jwt
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "saas_enterprise.db")
LOCAL_XML_FILE = os.path.join(BASE_DIR, "Master.xml")

def sanitize_xml(xml_content):
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode('utf-8', errors='ignore')
    xml_content = re.sub(r'&#[0-9]+;', '', xml_content)
    xml_content = re.sub(r'&#x[0-9a-fA-F]+;', '', xml_content)
    xml_content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml_content)
    return xml_content

def parse_and_seed_xml_content(raw_xml, company_code='10000'):
    try:
        cleaned_xml = sanitize_xml(raw_xml)
        root = ET.fromstring(cleaned_xml)

        p_count = 0
        i_count = 0
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        for ledger in root.findall('.//LEDGER'):
            name = ledger.get('NAME') or ledger.findtext('NAME', '')
            if name:
                gstin = ledger.findtext('PARTYGSTIN', '') or ledger.findtext('GSTIN', '') or ''
                gst_type = 'Registered / Regular' if gstin else 'Unregistered / URD'
                
                # Strict extraction: If missing in XML, leave completely BLANK (no dummy numbers)
                mobile = ledger.findtext('LEDGERPHONE', '') or ledger.findtext('MOBILE', '') or ledger.findtext('PHONE', '') or ''
                
                # Dynamic multiline ADDRESS extraction: If missing, leave BLANK
                addr_lines = []
                address_node = ledger.find('ADDRESS.LIST')
                if address_node is not None:
                    for line in address_node.findall('ADDRESS'):
                        if line.text and line.text.strip():
                            addr_lines.append(line.text.strip())
                if not addr_lines:
                    for addr_elem in ledger.findall('ADDRESS'):
                        if addr_elem.text and addr_elem.text.strip():
                            addr_lines.append(addr_elem.text.strip())
                
                full_address = ", ".join(addr_lines) if addr_lines else ''

                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO tally_parties (company_code, party_name, gst_status, gstin, mobile, address, state, city_beat, is_deleted)
                        VALUES (?, ?, ?, ?, ?, ?, 'Madhya Pradesh', 'Ratlam', 0)
                    ''', (company_code, name, gst_type, gstin, mobile, full_address))
                    p_count += 1
                except:
                    pass

        for item in root.findall('.//STOCKITEM'):
            iname = item.get('NAME') or item.findtext('NAME', '')
            if iname:
                uom = item.findtext('BASEUNITS', 'Pcs')
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO tally_items (company_code, item_name, stock_group, uom, default_rate)
                        VALUES (?, ?, 'General', ?, 0.0)
                    ''', (company_code, iname, uom))
                    i_count += 1
                except:
                    pass

        conn.commit()
        conn.close()
        print(f"🎉 XML Auto-Seeded: {p_count} Parties, {i_count} Items.")
    except Exception as e:
        print(f"Auto XML Seed Error: {e}")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT UNIQUE,
            company_name TEXT,
            status TEXT DEFAULT 'Active'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT,
            user_id TEXT UNIQUE,
            password TEXT,
            full_name TEXT,
            email TEXT DEFAULT '',
            mobile TEXT DEFAULT '',
            role TEXT,
            assigned_state TEXT DEFAULT 'Madhya Pradesh',
            assigned_city TEXT DEFAULT 'Ratlam',
            current_token TEXT DEFAULT '',
            status TEXT DEFAULT 'Active'
        )
    ''')

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN current_token TEXT DEFAULT ''")
    except:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tally_parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT,
            party_name TEXT UNIQUE,
            party_type TEXT DEFAULT 'Sundry Debtors',
            gst_status TEXT DEFAULT 'Unregistered / URD',
            gstin TEXT DEFAULT '',
            mobile TEXT DEFAULT '',
            address TEXT DEFAULT '',
            state TEXT DEFAULT 'Madhya Pradesh',
            city_beat TEXT DEFAULT 'Ratlam',
            is_deleted INTEGER DEFAULT 0,
            deleted_at TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tally_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT,
            item_name TEXT UNIQUE,
            stock_group TEXT DEFAULT 'General',
            uom TEXT DEFAULT 'Pcs',
            default_rate REAL DEFAULT 0.0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT,
            order_no TEXT UNIQUE,
            order_date TEXT,
            salesman_id TEXT,
            party_name TEXT,
            gst_status TEXT,
            assigned_state TEXT,
            city_village TEXT,
            items_json TEXT,
            grand_total REAL
        )
    ''')

    cursor.execute("INSERT OR IGNORE INTO companies (company_code, company_name) VALUES ('10000', 'New Mehta Sales Corporation')")
    cursor.execute("INSERT OR IGNORE INTO users (company_code, user_id, password, full_name, email, mobile, role, status) VALUES ('10000', 'admin', 'admin123', 'Company Admin Owner', 'admin@mehta.com', '', 'ADMIN', 'Active')")
    cursor.execute("INSERT OR IGNORE INTO users (company_code, user_id, password, full_name, email, mobile, role, assigned_state, assigned_city, status) VALUES ('10000', 'NMS1', 'pass123', 'Dinesh', 'dinesh@mehta.com', '', 'SALESMAN', 'Madhya Pradesh', 'Ratlam', 'Active')")

    conn.commit()
    conn.close()

    if os.path.exists(LOCAL_XML_FILE):
        try:
            with open(LOCAL_XML_FILE, 'rb') as f:
                raw_bytes = f.read()
                parse_and_seed_xml_content(raw_bytes, '10000')
        except Exception as e:
            print(f"Error reading local Master.xml: {e}")

init_db()

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('x-access-token')
        if not token:
            return jsonify({'status': 'error', 'message': 'Access Denied! Token Missing.'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['user_id']
            current_role = data['role']
            company_code = data['company_code']

            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT current_token FROM users WHERE LOWER(user_id) = LOWER(?)", (current_user,))
            row = cursor.fetchone()
            conn.close()

            if not row or row[0] != token:
                return jsonify({'status': 'session_expired', 'message': 'Logged in from another device!'}), 401

        except:
            return jsonify({'status': 'error', 'message': 'Invalid Token or Session Expired.'}), 401
        return f(current_user, current_role, company_code, *args, **kwargs)
    return decorated

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>New Mehta Sales Corporation - Order Portal</title>
    <style>
        * { box-sizing: border-box; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
        body { background: #0f172a; color: #0f172a; margin: 0; padding: 10px 5px; font-size: 16px; }
        
        .app-container { max-width: 480px; margin: 0 auto; background: #f8fafc; border-radius: 12px; min-height: 95vh; padding: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        
        .header { background: linear-gradient(135deg, #1e3a8a, #0f172a); color: white; padding: 18px 10px; border-radius: 10px; text-align: center; margin-bottom: 15px; }
        .header h1 { margin: 0; font-size: 24px; font-weight: 800; letter-spacing: 0.5px; line-height: 1.2; text-transform: uppercase; }
        .header h3 { margin: 6px 0 0 0; font-size: 16px; font-weight: 500; color: #93c5fd; text-transform: uppercase; letter-spacing: 1px; }
        
        .card { background: #ffffff; padding: 16px; border-radius: 10px; margin-top: 12px; border: 1px solid #e2e8f0; box-shadow: 0 2px 6px rgba(0,0,0,0.05); }
        
        label { font-size: 15px; font-weight: 600; color: #334155; margin-bottom: 4px; display: block; }
        select, input { width: 100%; padding: 12px 14px; border: 1.5px solid #cbd5e1; border-radius: 8px; font-size: 16px; color: #0f172a; background: #fff; outline: none; transition: 0.2s; }
        select:focus, input:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2); }
        
        .btn { background-color: #1e3a8a; color: white; padding: 14px; border: none; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 16px; width: 100%; text-align: center; }
        .btn-add { background-color: #16a34a; }
        .btn-edit { background-color: #0284c7; padding: 6px 10px; font-size: 13px; width: auto; }
        .btn-warn { background-color: #d97706; padding: 6px 10px; font-size: 13px; width: auto; }
        .btn-danger { background-color: #dc2626; padding: 6px 10px; font-size: 13px; width: auto; }
        .btn-link { background: none; border: none; color: #0284c7; cursor: pointer; text-decoration: underline; font-size: 15px; padding: 0; margin-top: 10px; }
        
        .table-responsive { overflow-x: auto; -webkit-overflow-scrolling: touch; margin-top: 10px; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { border: 1px solid #cbd5e1; padding: 8px 6px; text-align: left; }
        th { background-color: #1e3a8a; color: white; font-size: 13px; }
        
        .badge { padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; color: white; display: inline-block; }
        .badge-urd { background: #d97706; }
        .badge-reg { background: #16a34a; }
        
        .order-form { background: #ffffff; border: 2px solid #2563eb; padding: 14px; border-radius: 10px; margin-top: 15px; }
        .tally-box { background: #f0fdf4; border: 1px solid #16a34a; padding: 12px; border-radius: 8px; margin-bottom: 12px; }
        .menu-btn { background: #0284c7; color: white; border: none; padding: 12px; border-radius: 8px; font-weight: bold; cursor: pointer; font-size: 14px; flex: 1 1 45%; }
        
        .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); align-items:center; justify-content:center; z-index:999; padding:10px; }
        .modal-content { background:white; color:#0f172a; padding:18px; border-radius:12px; width:100%; max-width:450px; max-height:90vh; overflow-y:auto; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }
        
        .search-box-wrapper { position: relative; margin-bottom: 8px; }
        .search-box-wrapper input { padding-left: 36px; background: #f1f5f9; border-color: #cbd5e1; }
        .search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); font-size: 16px; color: #64748b; }
    </style>
</head>
<body>

    <div class="app-container">
        <div class="header">
            <h1>New Mehta Sales Corporation</h1>
            <h3>Order Portal</h3>
        </div>

        <!-- LOGIN BOX -->
        <div id="loginCard" class="card" style="margin-top: 20px;">
            <h3 style="margin-top:0; text-align:center; color:#1e3a8a; font-size:20px;">🔒 User Login</h3>
            <div style="margin-bottom:14px;">
                <label>User ID / Salesman ID:</label>
                <input type="text" id="loginUser" placeholder="e.g. admin or NMS1">
            </div>
            <div style="margin-bottom:18px;">
                <label>Password:</label>
                <input type="password" id="loginPass" placeholder="Password">
            </div>
            <button class="btn" onclick="doLogin()">🔐 Secure Login</button>
            <div style="text-align:center; margin-top:14px;">
                <button class="btn-link" onclick="openForgetModal()">🔑 Forget / Reset Password?</button>
            </div>
        </div>

        <!-- MAIN DASHBOARD -->
        <div id="mainPortal" style="display:none;">
            <div style="display:flex; justify-content:space-between; align-items:center; background:#e2e8f0; padding:10px 12px; border-radius:8px;">
                <div style="font-size:15px; font-weight:bold;">👤 <span id="userName">User</span> (<span id="userRole">Role</span>)</div>
                <button class="btn btn-danger" style="padding:6px 12px; font-size:13px;" onclick="logout()">Logout</button>
            </div>

            <!-- ADMIN XML IMPORT PANEL -->
            <div id="tallyImportPanel" class="tally-box" style="display:none; margin-top:12px;">
                <h4 style="margin:0 0 8px 0; color:#166534; font-size:15px;">💻 Admin: Re-Import Master.xml</h4>
                <input type="file" id="tallyXmlFile" accept=".xml" style="margin-bottom:8px; font-size:13px;">
                <button class="btn btn-add" style="padding:10px; font-size:14px;" onclick="uploadTallyXml()">📥 Update XML Data</button>
            </div>

            <!-- ACCOUNT INFO MODULE -->
            <div class="card" style="background:#f1f5f9; border:1px solid #cbd5e1; margin-top:12px; padding:12px;">
                <h4 style="margin:0 0 10px 0; color:#1e3a8a; font-size:16px;">📁 ACCOUNT INFO (Parties Master)</h4>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">
                    <button class="menu-btn" style="background:#16a34a;" onclick="openPartyModal('CREATE')">➕ CREATE Party</button>
                    <button class="menu-btn" style="background:#0284c7;" onclick="openViewModal('DISPLAY')">🔍 DISPLAY List</button>
                    <button class="menu-btn" style="background:#d97706;" onclick="openViewModal('ALTER')">✏️ ALTER / Edit</button>
                    <button class="menu-btn" style="background:#dc2626;" onclick="openTrashModal()">🗑️ Trash Bin</button>
                </div>
            </div>

            <!-- FIELD SALES ORDER FORM -->
            <div class="order-form">
                <h4 style="margin:0 0 12px 0; color:#1e3a8a; font-size:18px;" id="formTitle">📦 Book Sales Order</h4>
                <input type="hidden" id="editOrderNo" value="">

                <div style="margin-bottom:10px;">
                    <label>1. State:</label>
                    <select id="ordState">
                        <option value="Madhya Pradesh">Madhya Pradesh</option>
                        <option value="Gujarat">Gujarat</option>
                        <option value="Maharashtra">Maharashtra</option>
                        <option value="Rajasthan">Rajasthan</option>
                    </select>
                </div>
                
                <div style="margin-bottom:10px;">
                    <label>2. Beat / City:</label>
                    <select id="ordCity" onchange="filterOrderParties()">
                        <option value="Ratlam">Ratlam</option>
                        <option value="Ujjain">Ujjain</option>
                        <option value="Indore">Indore</option>
                    </select>
                </div>

                <div style="margin-bottom:12px;">
                    <label>3. Search & Select Party Name (Hindi/Eng):</label>
                    <div class="search-box-wrapper">
                        <span class="search-icon">🔍</span>
                        <input type="text" id="partySearchInput" placeholder="Type name (हिंदी / English)..." oninput="filterPartyListBySearch()">
                    </div>
                    <select id="ordParty" size="4" style="height: 110px;" onchange="updateSelectedPartyCard()">
                        <!-- Dynamic Options -->
                    </select>
                </div>

                <div id="partyCardInfo" style="display:none; background:#e0f2fe; padding:10px; border-radius:8px; margin-bottom:12px; font-size:14px; color:#0369a1; border:1px solid #bae6fd;">
                    <b>GST Type:</b> <span id="cardGst">--</span><br>
                    <b>Mobile:</b> <span id="cardMobile">--</span><br>
                    <b>Address:</b> <span id="cardAddr">--</span>
                </div>

                <hr style="margin:15px 0; border:0; border-top:1px solid #cbd5e1;">
                
                <h4 style="margin:0 0 10px 0; color:#1e3a8a; font-size:16px;">🛒 Add Items:</h4>
                <div id="orderItemsContainer">
                    <!-- Multi-Item Rows -->
                </div>

                <button class="btn btn-edit" style="margin-top:8px; width:100%; padding:10px;" onclick="addOrderItemRow()">➕ Add Stock Item Row</button>

                <div style="margin-top:15px; text-align:right; font-size:19px; font-weight:bold; color:#166534; background:#dcfce7; padding:10px; border-radius:6px;">
                    Total Amount: ₹<span id="grandOrderTotal">0.00</span>
                </div>

                <button class="btn btn-add" id="submitOrderBtn" style="margin-top:15px;" onclick="submitSalesOrder()">📝 Confirm & Submit Order</button>
            </div>

            <h4 style="margin-top:20px; font-size:18px;">📑 Recent Orders Audit</h4>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>Order Details</th>
                            <th>Items & Total</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="ordersAuditBody">
                        <tr><td colspan="3">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <!-- ORDER CONFIRMATION SUCCESS POP-UP MODAL -->
    <div id="orderSuccessModal" class="modal">
        <div class="modal-content" style="text-align:center;">
            <div style="font-size:48px; margin-bottom:10px;">🎉</div>
            <h3 style="margin:0; color:#166534; font-size:20px;">Order Confirmed!</h3>
            <p style="font-size:14px; color:#64748b; margin-top:4px;">Order has been successfully registered.</p>
            
            <div style="background:#f1f5f9; padding:12px; border-radius:8px; text-align:left; font-size:14px; margin:15px 0; line-height:1.6;">
                <b>Order No:</b> <span id="popOrdNo">--</span><br>
                <b>Party Name:</b> <span id="popParty">--</span><br>
                <b>Total Items:</b> <span id="popItemsCount">--</span><br>
                <b>Grand Total:</b> <b style="color:#166534; font-size:16px;">₹<span id="popGrandTotal">0.00</span></b>
            </div>

            <button class="btn btn-add" onclick="closeModal('orderSuccessModal')">👍 Okay, Got It!</button>
        </div>
    </div>

    <!-- FORGET PASSWORD MODAL -->
    <div id="forgetModal" class="modal">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#1e3a8a;">🔑 Reset Password</h3>
            <p style="font-size:14px; color:#64748b;">Enter Registered User ID, Email, or Mobile:</p>
            <div style="margin-bottom:14px;">
                <input type="text" id="resetQuery" placeholder="User ID / Email / Mobile">
            </div>
            <button class="btn btn-add" onclick="sendResetVerification()">Verify & Reset</button>
            <button class="btn btn-danger" style="width:100%; margin-top:10px;" onclick="closeModal('forgetModal')">Close Window</button>
        </div>
    </div>

    <!-- CREATE / ALTER PARTY MODAL -->
    <div id="partyModal" class="modal">
        <div class="modal-content">
            <h3 id="modalTitle" style="margin-top:0; color:#1e3a8a; font-size:18px;">Party Master</h3>
            <input type="hidden" id="modalMode" value="CREATE">
            <input type="hidden" id="modalOrigName" value="">
            
            <div style="margin-bottom:10px;">
                <label>Party / Shop Name:</label>
                <input type="text" id="pName" placeholder="Full Party Name">
            </div>
            <div style="margin-bottom:10px;">
                <label>GST Registration Status:</label>
                <select id="pGstStatus">
                    <option value="Unregistered / URD">Unregistered / URD</option>
                    <option value="Registered / Regular">Registered / Regular</option>
                    <option value="Composition">Composition</option>
                </select>
            </div>
            <div style="margin-bottom:10px;">
                <label>GSTIN Number (Optional):</label>
                <input type="text" id="pGstin" placeholder="GSTIN">
            </div>
            <div style="margin-bottom:10px;">
                <label>Mobile Number:</label>
                <input type="tel" id="pMobile" placeholder="Mobile Number">
            </div>
            <div style="margin-bottom:10px;">
                <label>City / Beat:</label>
                <input type="text" id="pCity" placeholder="e.g. Ratlam">
            </div>
            <div style="margin-bottom:15px;">
                <label>Address Details:</label>
                <input type="text" id="pAddress" placeholder="Full Address">
            </div>

            <div style="display:flex; gap:10px;">
                <button class="btn btn-danger" style="flex:1;" onclick="closeModal('partyModal')">Close</button>
                <button id="modalSaveBtn" class="btn btn-add" style="flex:1;" onclick="savePartyMaster()">Save Party</button>
            </div>
        </div>
    </div>

    <!-- DISPLAY / ALTER VIEW MODAL -->
    <div id="viewPartiesModal" class="modal">
        <div class="modal-content">
            <h3 id="viewModalTitle" style="margin-top:0; color:#1e3a8a; font-size:18px;">Party List</h3>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>Party Details</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="viewPartiesBody">
                        <!-- Populated dynamically -->
                    </tbody>
                </table>
            </div>
            <button class="btn btn-danger" style="width:100%; margin-top:15px;" onclick="closeModal('viewPartiesModal')">Close Window</button>
        </div>
    </div>

    <!-- TRASH MODAL -->
    <div id="trashModal" class="modal">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#dc2626; font-size:18px;">🗑️ Deleted Parties Trash</h3>
            <div class="table-responsive">
                <table>
                    <thead>
                        <tr>
                            <th>Party Name</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody id="trashPartiesBody">
                        <!-- Populated dynamically -->
                    </tbody>
                </table>
            </div>
            <button class="btn btn-danger" style="width:100%; margin-top:15px;" onclick="closeModal('trashModal')">Close Window</button>
        </div>
    </div>

    <datalist id="masterItemsDatalist"></datalist>

    <script>
        var authToken = localStorage.getItem('jwt_token');
        var masterPartiesList = [];
        var masterItemsList = [];
        var masterOrdersList = [];
        var orderItemRowIndex = 0;

        window.onload = function() {
            if(authToken) {
                fetch('/api/verify-token', {
                    headers: { 'x-access-token': authToken }
                })
                .then(res => res.json())
                .then(data => {
                    if(data.status === 'success') {
                        loadPortal(data);
                    } else {
                        localStorage.removeItem('jwt_token');
                        authToken = null;
                    }
                })
                .catch(() => {
                    localStorage.removeItem('jwt_token');
                    authToken = null;
                });
            }
        };

        function doLogin() {
            var u = document.getElementById('loginUser').value.trim();
            var p = document.getElementById('loginPass').value;

            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: u, password: p })
            })
            .then(res => res.json())
            .then(data => {
                if(data.status === 'success') {
                    localStorage.setItem('jwt_token', data.token);
                    authToken = data.token;
                    loadPortal(data);
                } else {
                    alert(data.message);
                }
            });
        }

        function loadPortal(userData) {
            document.getElementById('loginCard').style.display = 'none';
            document.getElementById('mainPortal').style.display = 'block';

            document.getElementById('userName').innerText = userData.full_name;
            document.getElementById('userRole').innerText = userData.role;

            if(userData.role === 'ADMIN') {
                document.getElementById('tallyImportPanel').style.display = 'block';
            }

            fetchPartyMastersList();
            fetchItemMastersList();
            fetchOrders();
        }

        function fetchPartyMastersList() {
            fetch('/api/get-tally-parties', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => handleApiResponse(res))
            .then(parties => {
                if(parties) {
                    masterPartiesList = parties;
                    filterOrderParties();
                }
            });
        }

        function fetchItemMastersList() {
            fetch('/api/get-tally-items', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => handleApiResponse(res))
            .then(items => {
                if(items) {
                    masterItemsList = items;
                    updateItemDatalist();
                    if(document.getElementById('orderItemsContainer').children.length === 0) {
                        addOrderItemRow();
                    }
                }
            });
        }

        function updateItemDatalist() {
            var datalist = document.getElementById('masterItemsDatalist');
            datalist.innerHTML = '';
            masterItemsList.forEach(i => {
                datalist.innerHTML += `<option value="${i.item_name}">${i.item_name} [${i.uom}]</option>`;
            });
        }

        function filterOrderParties() {
            document.getElementById('partySearchInput').value = '';
            filterPartyListBySearch();
        }

        function filterPartyListBySearch() {
            var city = document.getElementById('ordCity').value;
            var searchText = document.getElementById('partySearchInput').value.toLowerCase();
            var sel = document.getElementById('ordParty');
            sel.innerHTML = '';

            var filtered = masterPartiesList.filter(p => (p.city_beat === city || city === 'All') && p.party_name.toLowerCase().includes(searchText));
            filtered.forEach(p => {
                sel.innerHTML += `<option value="${p.party_name}">${p.party_name} (${p.gst_status})</option>`;
            });
            updateSelectedPartyCard();
        }

        function addOrderItemRow(itemVal = '', rateVal = '', qtyVal = '1') {
            orderItemRowIndex++;
            var container = document.getElementById('orderItemsContainer');
            var rowId = `itemRow_${orderItemRowIndex}`;

            var html = `<div id="${rowId}" style="background:#f1f5f9; padding:10px; border-radius:8px; border:1px solid #cbd5e1; margin-bottom:10px;">
                <div style="margin-bottom:6px;">
                    <label style="font-size:13px;">🔍 Select Item:</label>
                    <input type="text" class="row-item-input" value="${itemVal}" list="masterItemsDatalist" placeholder="Type stock item name..." onchange="calcGrandTotal()" oninput="calcGrandTotal()">
                </div>
                <div style="display:flex; gap:8px; margin-bottom:6px;">
                    <div style="flex:1;">
                        <label style="font-size:13px;">Rate (₹):</label>
                        <input type="number" class="row-item-rate" value="${rateVal}" placeholder="Rate" step="any" oninput="calcGrandTotal()">
                    </div>
                    <div style="flex:1;">
                        <label style="font-size:13px;">Qty:</label>
                        <input type="number" class="row-item-qty" value="${qtyVal}" step="any" oninput="calcGrandTotal()">
                    </div>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div><b>Row Total: ₹<span class="row-item-total-text">0.00</span></b></div>
                    <button class="btn btn-danger" style="padding:6px 12px; font-size:13px;" onclick="removeOrderItemRow('${rowId}')">❌ Remove</button>
                </div>
            </div>`;

            container.insertAdjacentHTML('beforeend', html);
            calcGrandTotal();
        }

        function removeOrderItemRow(rowId) {
            var row = document.getElementById(rowId);
            if(row) {
                row.remove();
                calcGrandTotal();
            }
        }

        function calcGrandTotal() {
            var container = document.getElementById('orderItemsContainer');
            var rows = container.children;
            var grandTotal = 0;

            Array.from(rows).forEach(r => {
                var rate = parseFloat(r.querySelector('.row-item-rate').value || 0);
                var qty = parseFloat(r.querySelector('.row-item-qty').value || 0);
                var rowTotal = rate * qty;
                r.querySelector('.row-item-total-text').innerText = rowTotal.toFixed(2);
                grandTotal += rowTotal;
            });

            document.getElementById('grandOrderTotal').innerText = grandTotal.toFixed(2);
        }

        function updateSelectedPartyCard() {
            var name = document.getElementById('ordParty').value;
            var party = masterPartiesList.find(p => p.party_name === name);

            if(party) {
                document.getElementById('partyCardInfo').style.display = 'block';
                document.getElementById('cardGst').innerText = party.gst_status + (party.gstin ? ' ('+party.gstin+')' : '');
                document.getElementById('cardMobile').innerText = party.mobile ? party.mobile : '--';
                document.getElementById('cardAddr').innerText = party.address ? party.address : '--';
            } else {
                document.getElementById('partyCardInfo').style.display = 'none';
            }
        }

        function submitSalesOrder() {
            var editNo = document.getElementById('editOrderNo').value;
            var state = document.getElementById('ordState').value;
            var city = document.getElementById('ordCity').value;
            var party = document.getElementById('ordParty').value;

            if(!party) return alert('Please select a Party!');

            var items = [];
            var container = document.getElementById('orderItemsContainer');
            var rows = container.children;

            Array.from(rows).forEach(r => {
                var itemName = r.querySelector('.row-item-input').value.trim();
                var rate = parseFloat(r.querySelector('.row-item-rate').value || 0);
                var qty = parseFloat(r.querySelector('.row-item-qty').value || 0);
                var total = rate * qty;

                if(itemName && rate > 0 && qty > 0) {
                    items.push({ item_name: itemName, rate: rate, qty: qty, total: total });
                }
            });

            if(items.length === 0) return alert('Please add at least 1 valid Item!');

            var grandTotal = parseFloat(document.getElementById('grandOrderTotal').innerText || 0);
            var pObj = masterPartiesList.find(p => p.party_name === party);
            var gstStatus = pObj ? pObj.gst_status : 'URD';

            var payload = { order_no: editNo, state: state, city: city, party_name: party, gst_status: gstStatus, items: items, grand_total: grandTotal };

            fetch('/api/create-order-multi', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify(payload)
            })
            .then(res => handleApiResponse(res))
            .then(data => {
                if(data && data.status === 'success') {
                    document.getElementById('popOrdNo').innerText = data.order_no;
                    document.getElementById('popParty').innerText = party;
                    document.getElementById('popItemsCount').innerText = items.length;
                    document.getElementById('popGrandTotal').innerText = grandTotal.toFixed(2);
                    
                    document.getElementById('orderSuccessModal').style.display = 'flex';
                    
                    resetOrderForm();
                    fetchOrders();
                }
            });
        }

        function resetOrderForm() {
            document.getElementById('editOrderNo').value = '';
            document.getElementById('formTitle').innerText = '📦 Book Sales Order';
            document.getElementById('submitOrderBtn').innerText = '📝 Confirm & Submit Order';
            document.getElementById('ordParty').value = '';
            document.getElementById('orderItemsContainer').innerHTML = '';
            addOrderItemRow();
            updateSelectedPartyCard();
        }

        function editOrder(orderNo) {
            var order = masterOrdersList.find(o => o.order_no === orderNo);
            if(!order) return;

            document.getElementById('editOrderNo').value = order.order_no;
            document.getElementById('formTitle').innerText = `✏️ Edit Order: ${order.order_no}`;
            document.getElementById('submitOrderBtn').innerText = '💾 Save Updated Order';

            document.getElementById('ordState').value = order.assigned_state || 'Madhya Pradesh';
            document.getElementById('ordCity').value = order.city_village || 'Ratlam';
            filterOrderParties();
            
            document.getElementById('ordParty').value = order.party_name;
            updateSelectedPartyCard();

            var container = document.getElementById('orderItemsContainer');
            container.innerHTML = '';

            if(order.items && order.items.length > 0) {
                order.items.forEach(i => {
                    addOrderItemRow(i.item_name, i.rate, i.qty);
                });
            } else {
                addOrderItemRow();
            }

            window.scrollTo({ top: 150, behavior: 'smooth' });
        }

        function deleteOrder(orderNo) {
            if(!confirm(`Are you sure you want to cancel / delete Order '${orderNo}'?`)) return;

            fetch('/api/delete-order', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify({ order_no: orderNo })
            })
            .then(res => handleApiResponse(res))
            .then(data => {
                if(data) {
                    alert(data.message);
                    fetchOrders();
                }
            });
        }

        function handleApiResponse(res) {
            if(res.status === 401) {
                alert("⚠️ Session expired or logged in from another device!");
                logout();
                return null;
            }
            return res.json();
        }

        function openViewModal(mode) {
            document.getElementById('viewModalTitle').innerText = mode === 'DISPLAY' ? '🔍 DISPLAY Parties' : '✏️ ALTER / Edit Parties';
            var tbody = document.getElementById('viewPartiesBody');
            tbody.innerHTML = '';

            masterPartiesList.forEach(p => {
                var badge = p.gst_status.includes('URD') ? `<span class="badge badge-urd">${p.gst_status}</span>` : `<span class="badge badge-reg">${p.gst_status}</span>`;
                var pJson = encodeURIComponent(JSON.stringify(p));

                var btnHtml = mode === 'DISPLAY' ? 
                    `<button class="btn btn-warn" onclick="openPartyModal('DISPLAY', '${pJson}')">🔍 View</button>` :
                    `<button class="btn btn-edit" onclick="openPartyModal('ALTER', '${pJson}')">✏️ Edit</button> <button class="btn btn-danger" onclick="deletePartySoft('${p.party_name}')">🗑️ Delete</button>`;

                tbody.innerHTML += `<tr>
                    <td><b>${p.party_name}</b><br><small>${p.mobile || '--'} | ${p.city_beat}</small><br>${badge}</td>
                    <td>${btnHtml}</td>
                </tr>`;
            });

            document.getElementById('viewPartiesModal').style.display = 'flex';
        }

        function openTrashModal() {
            fetch('/api/get-deleted-parties', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => handleApiResponse(res))
            .then(deletedParties => {
                if(deletedParties) {
                    var tbody = document.getElementById('trashPartiesBody');
                    tbody.innerHTML = '';

                    if(deletedParties.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;">Trash Bin is Empty.</td></tr>';
                    } else {
                        deletedParties.forEach(p => {
                            tbody.innerHTML += `<tr>
                                <td><b>${p.party_name}</b><br><small>${p.deleted_at}</small></td>
                                <td><button class="btn btn-add" style="padding:6px 10px; font-size:12px;" onclick="restoreParty('${p.party_name}')">🔄 Restore</button></td>
                            </tr>`;
                        });
                    }
                    document.getElementById('trashModal').style.display = 'flex';
                }
            });
        }

        function openPartyModal(mode, pJson = '') {
            closeModal('viewPartiesModal');
            var modal = document.getElementById('partyModal');
            document.getElementById('modalMode').value = mode;

            var pName = document.getElementById('pName');
            var pGst = document.getElementById('pGstStatus');
            var pGstin = document.getElementById('pGstin');
            var pMob = document.getElementById('pMobile');
            var pCity = document.getElementById('pCity');
            var pAddr = document.getElementById('pAddress');
            var btn = document.getElementById('modalSaveBtn');

            if(mode === 'CREATE') {
                document.getElementById('modalTitle').innerText = '➕ CREATE Party Master';
                document.getElementById('modalOrigName').value = '';
                pName.value = ''; pName.disabled = false;
                pGst.value = 'Unregistered / URD'; pGst.disabled = false;
                pGstin.value = ''; pGstin.disabled = false;
                pMob.value = ''; pMob.disabled = false;
                pCity.value = 'Ratlam'; pCity.disabled = false;
                pAddr.value = ''; pAddr.disabled = false;
                btn.style.display = 'block';
                btn.innerText = 'Save New Party';
            } else {
                var p = JSON.parse(decodeURIComponent(pJson));
                document.getElementById('modalOrigName').value = p.party_name;
                pName.value = p.party_name;
                pGst.value = p.gst_status;
                pGstin.value = p.gstin;
                pMob.value = p.mobile;
                pCity.value = p.city_beat;
                pAddr.value = p.address;

                if(mode === 'DISPLAY') {
                    document.getElementById('modalTitle').innerText = '🔍 DISPLAY Party Master';
                    pName.disabled = true; pGst.disabled = true; pGstin.disabled = true;
                    pMob.disabled = true; pCity.disabled = true; pAddr.disabled = true;
                    btn.style.display = 'none';
                } else if(mode === 'ALTER') {
                    document.getElementById('modalTitle').innerText = '✏️ ALTER Party Master';
                    pName.disabled = false; pGst.disabled = false; pGstin.disabled = false;
                    pMob.disabled = false; pCity.disabled = false; pAddr.disabled = false;
                    btn.style.display = 'block';
                    btn.innerText = '💾 Update Details';
                }
            }
            modal.style.display = 'flex';
        }

        function closeModal(id) {
            document.getElementById(id).style.display = 'none';
        }

        function savePartyMaster() {
            var mode = document.getElementById('modalMode').value;
            var origName = document.getElementById('modalOrigName').value;
            var name = document.getElementById('pName').value.trim();
            var gst = document.getElementById('pGstStatus').value;
            var gstin = document.getElementById('pGstin').value.trim();
            var mob = document.getElementById('pMobile').value.trim();
            var city = document.getElementById('pCity').value.trim();
            var addr = document.getElementById('pAddress').value.trim();

            if(!name || !mob || !city) return alert('Party Name, Mobile and City are compulsory!');

            fetch('/api/save-party-master', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify({ mode: mode, orig_name: origName, party_name: name, gst_status: gst, gstin: gstin, mobile: mob, city_beat: city, address: addr })
            })
            .then(res => handleApiResponse(res))
            .then(data => {
                if(data) {
                    alert(data.message);
                    closeModal('partyModal');
                    fetchPartyMastersList();
                }
            });
        }

        function deletePartySoft(partyName) {
            if(!confirm(`Delete '${partyName}'? (Kept in Trash for 30 Days)`)) return;

            fetch('/api/delete-party-soft', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify({ party_name: partyName })
            })
            .then(res => handleApiResponse(res))
            .then(data => {
                if(data) {
                    alert(data.message);
                    closeModal('viewPartiesModal');
                    fetchPartyMastersList();
                }
            });
        }

        function restoreParty(partyName) {
            fetch('/api/restore-party', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify({ party_name: partyName })
            })
            .then(res => handleApiResponse(res))
            .then(data => {
                if(data) {
                    alert(data.message);
                    closeModal('trashModal');
                    fetchPartyMastersList();
                }
            });
        }

        function uploadTallyXml() {
            var fileInput = document.getElementById('tallyXmlFile');
            if(fileInput.files.length === 0) return alert('Select master.xml file first!');

            var formData = new FormData();
            formData.append('file', fileInput.files[0]);

            fetch('/api/admin/import-tally-xml', {
                method: 'POST',
                headers: { 'x-access-token': authToken },
                body: formData
            })
            .then(res => handleApiResponse(res))
            .then(data => {
                if(data) {
                    alert(data.message);
                    fetchPartyMastersList();
                    fetchItemMastersList();
                }
            });
        }

        function fetchOrders() {
            fetch('/api/get-orders', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => handleApiResponse(res))
            .then(orders => {
                if(orders) {
                    masterOrdersList = orders;
                    var tbody = document.getElementById('ordersAuditBody');
                    tbody.innerHTML = '';
                    if(!orders || orders.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;">No orders found.</td></tr>';
                        return;
                    }
                    orders.forEach(o => {
                        var itemsDetail = '';
                        if(o.items && o.items.length > 0) {
                            o.items.forEach(i => {
                                itemsDetail += `• ${i.item_name} (₹${i.rate} x ${i.qty}) = ₹${i.total}<br>`;
                            });
                        }

                        tbody.innerHTML += `<tr>
                            <td><b>${o.order_no}</b><br><small>${o.date}</small><br><b>${o.party_name}</b> (${o.city_village})<br><small>By: ${o.salesman_id}</small></td>
                            <td><small>${itemsDetail}</small><br><b style="color:#166534; font-size:15px;">Total: ₹${o.grand_total}</b></td>
                            <td>
                                <button class="btn btn-edit" style="margin-bottom:4px;" onclick="editOrder('${o.order_no}')">✏️ Edit</button>
                                <button class="btn btn-danger" onclick="deleteOrder('${o.order_no}')">🗑️ Cancel</button>
                            </td>
                        </tr>`;
                    });
                }
            });
        }

        function openForgetModal() {
            document.getElementById('forgetModal').style.display = 'flex';
        }

        function sendResetVerification() {
            var q = document.getElementById('resetQuery').value.trim();
            if(!q) return alert('Enter Details!');

            fetch('/api/forget-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: q })
            })
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                closeModal('forgetModal');
            });
        }

        function logout() {
            localStorage.removeItem('jwt_token');
            location.reload();
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/verify-token', methods=['GET'])
@token_required
def verify_token(current_user, current_role, company_code):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT full_name FROM users WHERE LOWER(user_id) = LOWER(?)', (current_user,))
    user = cursor.fetchone()
    conn.close()
    
    return jsonify({
        "status": "success",
        "company_code": company_code,
        "user_id": current_user,
        "full_name": user[0] if user else current_user,
        "role": current_role
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    u_id = data.get('user_id', '').strip()
    pwd = data.get('password', '')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT company_code, user_id, full_name, role, status FROM users WHERE LOWER(user_id) = LOWER(?) AND password = ?', (u_id, pwd))
    user = cursor.fetchone()

    if user:
        if user[4] != 'Active':
            conn.close()
            return jsonify({"status": "error", "message": f"🚫 Account Restricted! Status: '{user[4]}'."}), 403

        token = jwt.encode({
            'company_code': user[0],
            'user_id': user[1],
            'role': user[3],
            'exp': datetime.now(timezone.utc) + timedelta(days=365)
        }, app.config['SECRET_KEY'], algorithm="HS256")

        cursor.execute("UPDATE users SET current_token = ? WHERE LOWER(user_id) = LOWER(?)", (token, u_id))
        conn.commit()
        conn.close()

        return jsonify({
            "status": "success",
            "token": token,
            "company_code": user[0],
            "user_id": user[1],
            "full_name": user[2],
            "role": user[3]
        })
    else:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid User ID or Password!"}), 401

@app.route('/api/forget-password', methods=['POST'])
def forget_password():
    data = request.json
    q = data.get('query', '').strip()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, email, mobile FROM users WHERE LOWER(user_id) = LOWER(?) OR LOWER(email) = LOWER(?) OR mobile = ?', (q, q, q))
    user = cursor.fetchone()
    conn.close()

    if user:
        return jsonify({
            "status": "success",
            "message": f"📩 Reset verification code issued for registered User ID: '{user[0]}'."
        })
    else:
        return jsonify({"status": "error", "message": "User ID, Email or Mobile not registered!"}), 404

@app.route('/api/get-tally-parties')
@token_required
def get_tally_parties(current_user, current_role, company_code):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT party_name, gst_status, gstin, mobile, address, state, city_beat FROM tally_parties WHERE company_code = ? AND is_deleted = 0 ORDER BY party_name ASC', (company_code,))
    parties = [{"party_name": r[0], "gst_status": r[1], "gstin": r[2], "mobile": r[3], "address": r[4], "state": r[5], "city_beat": r[6]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(parties)

@app.route('/api/get-deleted-parties')
@token_required
def get_deleted_parties(current_user, current_role, company_code):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT party_name, deleted_at FROM tally_parties WHERE company_code = ? AND is_deleted = 1 ORDER BY id DESC', (company_code,))
    parties = [{"party_name": r[0], "deleted_at": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(parties)

@app.route('/api/get-tally-items')
@token_required
def get_tally_items(current_user, current_role, company_code):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT item_name, stock_group, uom, default_rate FROM tally_items WHERE company_code = ? ORDER BY item_name ASC', (company_code,))
    items = [{"item_name": r[0], "stock_group": r[1], "uom": r[2], "default_rate": r[3]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(items)

@app.route('/api/save-party-master', methods=['POST'])
@token_required
def save_party_master(current_user, current_role, company_code):
    data = request.json
    mode = data.get('mode')
    orig_name = data.get('orig_name')
    p_name = data.get('party_name')
    gst_status = data.get('gst_status')
    gstin = data.get('gstin')
    mobile = data.get('mobile')
    city = data.get('city_beat')
    address = data.get('address')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if mode == 'CREATE':
        try:
            cursor.execute('''
                INSERT INTO tally_parties (company_code, party_name, gst_status, gstin, mobile, address, state, city_beat, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, 'Madhya Pradesh', ?, 0)
            ''', (company_code, p_name, gst_status, gstin, mobile, address, city))
            conn.commit()
            conn.close()
            return jsonify({"status": "success", "message": f"🎉 New Party Master '{p_name}' Saved!"})
        except:
            conn.close()
            return jsonify({"status": "error", "message": "Party Name already exists in Database!"})
    elif mode == 'ALTER':
        cursor.execute('''
            UPDATE tally_parties 
            SET party_name = ?, gst_status = ?, gstin = ?, mobile = ?, address = ?, city_beat = ?
            WHERE company_code = ? AND party_name = ?
        ''', (p_name, gst_status, gstin, mobile, address, city, company_code, orig_name))
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": f"✏️ Party Master '{p_name}' Updated!"})

    conn.close()
    return jsonify({"status": "error", "message": "Invalid Mode!"})

@app.route('/api/delete-party-soft', methods=['POST'])
@token_required
def delete_party_soft(current_user, current_role, company_code):
    data = request.json
    p_name = data.get('party_name')
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE tally_parties SET is_deleted = 1, deleted_at = ? WHERE company_code = ? AND party_name = ?', (now_str, company_code, p_name))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": f"🗑️ Party '{p_name}' Moved to Trash Bin!"})

@app.route('/api/restore-party', methods=['POST'])
@token_required
def restore_party(current_user, current_role, company_code):
    data = request.json
    p_name = data.get('party_name')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE tally_parties SET is_deleted = 0, deleted_at = NULL WHERE company_code = ? AND party_name = ?', (company_code, p_name))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": f"🔄 Party '{p_name}' Restored!"})

@app.route('/api/admin/import-tally-xml', methods=['POST'])
@token_required
def import_tally_xml(current_user, current_role, company_code):
    if current_role != 'ADMIN': return jsonify({"status": "error", "message": "Permission Denied!"}), 403
    if 'file' not in request.files: return jsonify({"status": "error", "message": "No file uploaded!"}), 400

    file = request.files['file']
    try:
        raw_bytes = file.read()
        parse_and_seed_xml_content(raw_bytes, company_code)
        return jsonify({"status": "success", "message": "🎉 Tally XML Parsed & Auto-Saved!"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"XML Parsing Error: {str(e)}"}), 500

@app.route('/api/create-order-multi', methods=['POST'])
@token_required
def create_order_multi(current_user, current_role, company_code):
    data = request.json
    ord_no = data.get('order_no') or f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    ord_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    import json
    items_json_str = json.dumps(data.get('items', []))

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if data.get('order_no'):
        cursor.execute('''
            UPDATE orders 
            SET party_name = ?, gst_status = ?, assigned_state = ?, city_village = ?, items_json = ?, grand_total = ?
            WHERE company_code = ? AND order_no = ?
        ''', (data.get('party_name'), data.get('gst_status'), data.get('state'), data.get('city'), items_json_str, data.get('grand_total'), company_code, ord_no))
    else:
        cursor.execute('''
            INSERT INTO orders (company_code, order_no, order_date, salesman_id, party_name, gst_status, assigned_state, city_village, items_json, grand_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (company_code, ord_no, ord_date, current_user, data.get('party_name'), data.get('gst_status'), data.get('state'), data.get('city'), items_json_str, data.get('grand_total')))
    
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "order_no": ord_no, "message": f"🎉 Multi-Item Order '{ord_no}' Saved Successfully!"})

@app.route('/api/delete-order', methods=['POST'])
@token_required
def delete_order(current_user, current_role, company_code):
    data = request.json
    ord_no = data.get('order_no')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM orders WHERE company_code = ? AND order_no = ?', (company_code, ord_no))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": f"🗑️ Order '{ord_no}' Cancelled and Deleted!"})

@app.route('/api/get-orders')
@token_required
def get_orders(current_user, current_role, company_code):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if current_role == 'ADMIN':
        cursor.execute('SELECT order_no, order_date, party_name, gst_status, city_village, items_json, salesman_id, grand_total, assigned_state FROM orders WHERE company_code = ? ORDER BY id DESC', (company_code,))
    else:
        cursor.execute('SELECT order_no, order_date, party_name, gst_status, city_village, items_json, salesman_id, grand_total, assigned_state FROM orders WHERE company_code = ? AND salesman_id = ? ORDER BY id DESC', (company_code, current_user))

    import json
    rows = []
    for r in cursor.fetchall():
        items_arr = json.loads(r[5]) if r[5] else []
        rows.append({
            "order_no": r[0],
            "date": r[1],
            "party_name": r[2],
            "gst_status": r[3],
            "city_village": r[4],
            "items": items_arr,
            "salesman_id": r[6],
            "grand_total": r[7],
            "assigned_state": r[8]
        })

    conn.close()
    return jsonify(rows)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)