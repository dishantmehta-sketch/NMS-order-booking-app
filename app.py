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
                gstin = ledger.findtext('PARTYGSTIN', '')
                gst_type = 'Registered / Regular' if gstin else 'Unregistered / URD'
                mobile = ledger.findtext('LEDGERPHONE', '') or ledger.findtext('MOBILE', '') or '9898989898'
                address = ledger.findtext('ADDRESS', 'Market Area')
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO tally_parties (company_code, party_name, gst_status, gstin, mobile, address, state, city_beat, is_deleted)
                        VALUES (?, ?, ?, ?, ?, ?, 'Madhya Pradesh', 'Ratlam', 0)
                    ''', (company_code, name, gst_type, gstin, mobile, address))
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
            status TEXT DEFAULT 'Active'
        )
    ''')

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
            order_no TEXT,
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
    cursor.execute("INSERT OR IGNORE INTO users (company_code, user_id, password, full_name, email, mobile, role, status) VALUES ('10000', 'admin', 'admin123', 'Company Admin Owner', 'admin@mehta.com', '9898989898', 'ADMIN', 'Active')")
    cursor.execute("INSERT OR IGNORE INTO users (company_code, user_id, password, full_name, email, mobile, role, assigned_state, assigned_city, status) VALUES ('10000', 'NMS1', 'pass123', 'Dinesh', 'dinesh@mehta.com', '9797979797', 'SALESMAN', 'Madhya Pradesh', 'Ratlam', 'Active')")

    conn.commit()
    conn.close()

    # JUGAD: Auto Parse Master.xml if available in repository!
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
        except:
            return jsonify({'status': 'error', 'message': 'Invalid Token or Session Expired.'}), 401
        return f(current_user, current_role, company_code, *args, **kwargs)
    return decorated

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Mehta Sales Corporation Order Portal</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 10px; }
        .header { background: #1e3a8a; padding: 12px 20px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
        .card { background: #ffffff; color: #0f172a; padding: 20px; border-radius: 8px; margin-top: 15px; }
        .row { display: flex; gap: 10px; flex-wrap: wrap; }
        .col { flex: 1; min-width: 140px; }
        select, input { width: 100%; padding: 10px; border: 1px solid #cbd5e1; border-radius: 5px; font-size: 14px; box-sizing: border-box; }
        .btn { background-color: #1e3a8a; color: white; padding: 10px 16px; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }
        .btn-add { background-color: #16a34a; }
        .btn-edit { background-color: #0284c7; padding: 4px 8px; font-size: 11px; }
        .btn-warn { background-color: #d97706; padding: 4px 8px; font-size: 11px; }
        .btn-danger { background-color: #dc2626; padding: 4px 8px; font-size: 11px; }
        .btn-link { background: none; border: none; color: #0284c7; cursor: pointer; text-decoration: underline; font-size: 13px; padding: 0; margin-top: 10px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #cbd5e1; padding: 8px; text-align: left; font-size: 13px; }
        th { background-color: #1e3a8a; color: white; }
        .badge { padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; color: white; }
        .badge-urd { background: #d97706; }
        .badge-reg { background: #16a34a; }
        .order-form { background: #f8fafc; border: 2px solid #3b82f6; padding: 15px; border-radius: 8px; margin-top: 15px; }
        .tally-box { background: #f0fdf4; border: 1px solid #16a34a; padding: 12px; border-radius: 6px; margin-bottom: 15px; }
        .menu-btn { background: #0284c7; color: white; border: none; padding: 12px 18px; border-radius: 6px; font-weight: bold; cursor: pointer; }
        .modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); align-items:center; justify-content:center; z-index:999; }
        .modal-content { background:white; color:#0f172a; padding:20px; border-radius:8px; width:95%; max-width:700px; max-height:85vh; overflow-y:auto; }
    </style>
</head>
<body>
    <div class="header">
        <h2>🌐 New Mehta Sales Corporation Order Portal</h2>
        <span>System Status: <b>Auto-Sync Stock Connected</b></span>
    </div>

    <!-- LOGIN BOX -->
    <div id="loginCard" class="card" style="max-width: 400px; margin: 40px auto;">
        <h3 style="margin-top:0;">🔒 User Login Portal</h3>
        <div class="form-group" style="margin-bottom:12px;">
            <label>User ID / Salesman ID:</label>
            <input type="text" id="loginUser" placeholder="e.g. admin or NMS1">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
            <label>Password:</label>
            <input type="password" id="loginPass" placeholder="Password">
        </div>
        <button class="btn" style="width:100%;" onclick="doLogin()">🔐 Secure Login</button>
        <div style="text-align:center; margin-top:12px;">
            <button class="btn-link" onclick="openForgetModal()">🔑 Forget / Reset Password?</button>
        </div>
    </div>

    <!-- MAIN DASHBOARD -->
    <div id="mainPortal" class="card" style="display:none;">
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #e2e8f0; padding-bottom:10px;">
            <h3>Welcome, <span id="userName">User</span> (<span id="userRole">Role</span>)</h3>
            <button class="btn" style="width:auto; background:#dc2626;" onclick="logout()">Logout</button>
        </div>

        <!-- PC / ADMIN REAL XML IMPORT PANEL -->
        <div id="tallyImportPanel" class="tally-box" style="display:none; margin-top:15px;">
            <h4 style="margin-top:0; color:#166534;">💻 Admin PC Control: Manual Re-Import Tally XML File</h4>
            <div style="display:flex; gap:10px; align-items:center;">
                <input type="file" id="tallyXmlFile" accept=".xml">
                <button class="btn btn-add" style="width:220px;" onclick="uploadTallyXml()">📥 Parse & Update XML</button>
            </div>
        </div>

        <!-- TALLY ACCOUNT INFO HIERARCHY MODULE -->
        <div class="card" style="background:#f1f5f9; border:1px solid #cbd5e1; margin-top:15px;">
            <h4 style="margin-top:0; color:#1e3a8a;">📁 ACCOUNT INFO (Party Ledger Masters)</h4>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
                <button class="menu-btn" style="background:#16a34a;" onclick="openPartyModal('CREATE')">➕ CREATE Party</button>
                <button class="menu-btn" style="background:#0284c7;" onclick="openViewModal('DISPLAY')">🔍 DISPLAY Parties</button>
                <button class="menu-btn" style="background:#d97706;" onclick="openViewModal('ALTER')">✏️ ALTER Parties</button>
                <button class="menu-btn" style="background:#dc2626;" onclick="openTrashModal()">🗑️ DELETE Trash (30 Days Auto-Expire)</button>
            </div>
        </div>

        <!-- FIELD SALES MULTI-ITEM ORDER ENTRY FORM -->
        <div class="order-form">
            <h4 style="margin-top:0; color:#1e3a8a;">📦 Field Sales Order Booking (Auto-Loaded Persistent Stock)</h4>
            <div class="row" style="margin-bottom:10px;">
                <div class="col">
                    <label><b>1. State:</b></label>
                    <select id="ordState">
                        <option value="Madhya Pradesh">Madhya Pradesh</option>
                        <option value="Gujarat">Gujarat</option>
                        <option value="Maharashtra">Maharashtra</option>
                        <option value="Rajasthan">Rajasthan</option>
                    </select>
                </div>
                <div class="col">
                    <label><b>2. Beat / City:</b></label>
                    <select id="ordCity" onchange="filterOrderParties()">
                        <option value="Ratlam">Ratlam</option>
                        <option value="Ujjain">Ujjain</option>
                        <option value="Indore">Indore</option>
                    </select>
                </div>
                <div class="col">
                    <label><b>3. Select Customer / Party:</b></label>
                    <select id="ordParty" onchange="updateSelectedPartyCard()">
                        <option value="">-- Select Party --</option>
                    </select>
                </div>
            </div>

            <div id="partyCardInfo" style="display:none; background:#e0f2fe; padding:8px; border-radius:5px; margin-bottom:12px; font-size:12px; color:#0369a1;">
                <b>GST Type:</b> <span id="cardGst">--</span> | <b>Mobile:</b> <span id="cardMobile">--</span> | <b>Address:</b> <span id="cardAddr">--</span>
            </div>

            <hr style="margin:15px 0; border:0; border-top:1px solid #cbd5e1;">
            
            <h5 style="margin:0 0 10px 0; color:#1e3a8a;">🛒 Multi-Item Order Grid (Items Persistent):</h5>
            <div id="orderItemsContainer">
                <!-- Multi-Item Rows inserted dynamically -->
            </div>

            <button class="btn btn-edit" style="margin-top:10px; width:auto;" onclick="addOrderItemRow()">➕ Add Another Item Row</button>

            <div style="margin-top:15px; text-align:right; font-size:18px; font-weight:bold; color:#166534;">
                Grand Order Total: ₹<span id="grandOrderTotal">0.00</span>
            </div>

            <button class="btn btn-add" style="width:100%; font-size:16px; margin-top:15px;" onclick="submitSalesOrder()">📝 Submit Complete Sales Order</button>
        </div>

        <h4 style="margin-top:25px;">📑 Real-Time Orders Audit Trail</h4>
        <table>
            <thead>
                <tr>
                    <th>Order No</th>
                    <th>Date</th>
                    <th>Customer Party</th>
                    <th>City/Beat</th>
                    <th>Items Ordered Detail</th>
                    <th>Salesman ID</th>
                    <th>Grand Total Amount</th>
                </tr>
            </thead>
            <tbody id="ordersAuditBody">
                <tr><td colspan="7">Loading Orders...</td></tr>
            </tbody>
        </table>
    </div>

    <!-- FORGET / RESET PASSWORD MODAL -->
    <div id="forgetModal" class="modal">
        <div class="modal-content" style="max-width:400px;">
            <h3 style="margin-top:0; color:#1e3a8a;">🔑 Forget / Reset Password</h3>
            <p style="font-size:12px; color:#64748b;">Apni Registered User ID, Email ya Mobile Number Enter Karein:</p>
            <div class="form-group" style="margin-bottom:12px;">
                <input type="text" id="resetQuery" placeholder="User ID / Email / Mobile">
            </div>
            <button class="btn btn-add" style="width:100%;" onclick="sendResetVerification()">📩 Verify & Reset Password</button>
            <div style="text-align:center; margin-top:12px;">
                <button class="btn-danger" style="width:100%;" onclick="closeModal('forgetModal')">Close Window</button>
            </div>
        </div>
    </div>

    <!-- CREATE / ALTER PARTY MODAL -->
    <div id="partyModal" class="modal">
        <div class="modal-content">
            <h3 id="modalTitle" style="margin-top:0; color:#1e3a8a;">Party Master</h3>
            <input type="hidden" id="modalMode" value="CREATE">
            <input type="hidden" id="modalOrigName" value="">
            
            <div style="margin-bottom:10px;">
                <label style="font-size:12px;">Party / Shop Name:</label>
                <input type="text" id="pName" placeholder="Full Party Name">
            </div>
            <div style="margin-bottom:10px;">
                <label style="font-size:12px;">GST Registration Status:</label>
                <select id="pGstStatus">
                    <option value="Unregistered / URD">Unregistered / URD</option>
                    <option value="Registered / Regular">Registered / Regular</option>
                    <option value="Composition">Composition</option>
                </select>
            </div>
            <div style="margin-bottom:10px;">
                <label style="font-size:12px;">GSTIN Number (Optional):</label>
                <input type="text" id="pGstin" placeholder="GSTIN (if Registered)">
            </div>
            <div style="margin-bottom:10px;">
                <label style="font-size:12px;">Mobile Number:</label>
                <input type="tel" id="pMobile" placeholder="Mobile Number">
            </div>
            <div style="margin-bottom:10px;">
                <label style="font-size:12px;">City / Village / Beat:</label>
                <input type="text" id="pCity" placeholder="e.g. Ratlam">
            </div>
            <div style="margin-bottom:15px;">
                <label style="font-size:12px;">Address Details:</label>
                <input type="text" id="pAddress" placeholder="Full Address">
            </div>

            <div style="display:flex; justify-content:space-between; gap:10px;">
                <button class="btn btn-danger" style="width:50%;" onclick="closeModal('partyModal')">Close</button>
                <button id="modalSaveBtn" class="btn btn-add" style="width:50%;" onclick="savePartyMaster()">Save Party Master</button>
            </div>
        </div>
    </div>

    <!-- DISPLAY / ALTER VIEW MODAL -->
    <div id="viewPartiesModal" class="modal">
        <div class="modal-content">
            <h3 id="viewModalTitle" style="margin-top:0; color:#1e3a8a;">Party Masters List</h3>
            <table>
                <thead>
                    <tr>
                        <th>Party Name</th>
                        <th>GST Status</th>
                        <th>Mobile</th>
                        <th>Beat/City</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="viewPartiesBody">
                    <!-- Populated dynamically -->
                </tbody>
            </table>
            <button class="btn btn-danger" style="width:100%; margin-top:15px;" onclick="closeModal('viewPartiesModal')">Close View Window</button>
        </div>
    </div>

    <!-- 30-DAYS TRASH BIN MODAL -->
    <div id="trashModal" class="modal">
        <div class="modal-content">
            <h3 style="margin-top:0; color:#dc2626;">🗑️ Deleted Parties Trash (30 Days Auto-Expire)</h3>
            <p style="font-size:12px; color:#64748b;">Ye parties delete ki gayi hain aur 30 din baad permanently auto-delete ho jayengi:</p>
            <table>
                <thead>
                    <tr>
                        <th>Party Name</th>
                        <th>Deleted Date</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="trashPartiesBody">
                    <!-- Populated dynamically -->
                </tbody>
            </table>
            <button class="btn btn-danger" style="width:100%; margin-top:15px;" onclick="closeModal('trashModal')">Close Trash Window</button>
        </div>
    </div>

    <script>
        var authToken = localStorage.getItem('jwt_token');
        var masterPartiesList = [];
        var masterItemsList = [];
        var orderItemRowIndex = 0;

        function openForgetModal() {
            document.getElementById('forgetModal').style.display = 'flex';
        }

        function sendResetVerification() {
            var q = document.getElementById('resetQuery').value.trim();
            if(!q) return alert('User ID / Email / Mobile Enter Karein!');

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
            .then(res => res.json())
            .then(parties => {
                masterPartiesList = parties;
                filterOrderParties();
            });
        }

        function fetchItemMastersList() {
            fetch('/api/get-tally-items', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => res.json())
            .then(items => {
                masterItemsList = items;
                document.getElementById('orderItemsContainer').innerHTML = '';
                orderItemRowIndex = 0;
                addOrderItemRow();
            });
        }

        function addOrderItemRow() {
            orderItemRowIndex++;
            var container = document.getElementById('orderItemsContainer');
            var rowId = `itemRow_${orderItemRowIndex}`;

            var optionsHtml = '<option value="">-- Select Stock Item --</option>';
            if(masterItemsList && masterItemsList.length > 0) {
                masterItemsList.forEach(i => {
                    optionsHtml += `<option value="${i.item_name}">${i.item_name} [${i.uom}]</option>`;
                });
            }

            var html = `<div id="${rowId}" class="row" style="margin-bottom:10px; background:#ffffff; padding:10px; border-radius:5px; border:1px solid #cbd5e1; align-items:center;">
                <div class="col" style="flex:2;">
                    <label style="font-size:11px;"><b>Select Item:</b></label>
                    <select class="row-item-select" onchange="calcGrandTotal()">${optionsHtml}</select>
                </div>
                <div class="col">
                    <label style="font-size:11px;"><b>Rate (₹):</b></label>
                    <input type="number" class="row-item-rate" placeholder="Rate" step="any" oninput="calcGrandTotal()">
                </div>
                <div class="col">
                    <label style="font-size:11px;"><b>Quantity:</b></label>
                    <input type="number" class="row-item-qty" placeholder="Qty" value="1" step="any" oninput="calcGrandTotal()">
                </div>
                <div class="col">
                    <label style="font-size:11px;"><b>Row Total (₹):</b></label>
                    <input type="number" class="row-item-total" value="0.00" readonly style="background:#f1f5f9; font-weight:bold;">
                </div>
                <div style="width:40px; text-align:center;">
                    <button class="btn btn-danger" style="padding:8px 10px; margin-top:15px;" onclick="removeOrderItemRow('${rowId}')">❌</button>
                </div>
            </div>`;

            container.insertAdjacentHTML('beforeend', html);
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
            var rows = container.querySelectorAll('.row');
            var grandTotal = 0;

            rows.forEach(r => {
                var rate = parseFloat(r.querySelector('.row-item-rate').value || 0);
                var qty = parseFloat(r.querySelector('.row-item-qty').value || 0);
                var rowTotal = rate * qty;
                r.querySelector('.row-item-total').value = rowTotal.toFixed(2);
                grandTotal += rowTotal;
            });

            document.getElementById('grandOrderTotal').innerText = grandTotal.toFixed(2);
        }

        function filterOrderParties() {
            var city = document.getElementById('ordCity').value;
            var sel = document.getElementById('ordParty');
            sel.innerHTML = '<option value="">-- Select Party --</option>';

            var filtered = masterPartiesList.filter(p => p.city_beat === city || city === 'All');
            filtered.forEach(p => {
                sel.innerHTML += `<option value="${p.party_name}">${p.party_name} (${p.gst_status})</option>`;
            });
            updateSelectedPartyCard();
        }

        function updateSelectedPartyCard() {
            var name = document.getElementById('ordParty').value;
            var party = masterPartiesList.find(p => p.party_name === name);

            if(party) {
                document.getElementById('partyCardInfo').style.display = 'block';
                document.getElementById('cardGst').innerText = party.gst_status + (party.gstin ? ' ('+party.gstin+')' : '');
                document.getElementById('cardMobile').innerText = party.mobile || 'N/A';
                document.getElementById('cardAddr').innerText = party.address || 'N/A';
            } else {
                document.getElementById('partyCardInfo').style.display = 'none';
            }
        }

        function openViewModal(mode) {
            document.getElementById('viewModalTitle').innerText = mode === 'DISPLAY' ? '🔍 DISPLAY Party Masters List' : '✏️ ALTER Party Masters List';
            var tbody = document.getElementById('viewPartiesBody');
            tbody.innerHTML = '';

            masterPartiesList.forEach(p => {
                var badge = p.gst_status.includes('URD') ? `<span class="badge badge-urd">${p.gst_status}</span>` : `<span class="badge badge-reg">${p.gst_status}</span>`;
                var pJson = encodeURIComponent(JSON.stringify(p));

                var btnHtml = mode === 'DISPLAY' ? 
                    `<button class="btn btn-warn" onclick="openPartyModal('DISPLAY', '${pJson}')">🔍 View</button>` :
                    `<button class="btn btn-edit" onclick="openPartyModal('ALTER', '${pJson}')">✏️ Edit / Alter</button> <button class="btn btn-danger" onclick="deletePartySoft('${p.party_name}')">🗑️ Delete</button>`;

                tbody.innerHTML += `<tr>
                    <td><b>${p.party_name}</b></td>
                    <td>${badge}</td>
                    <td>${p.mobile}</td>
                    <td><b>${p.city_beat}</b></td>
                    <td>${btnHtml}</td>
                </tr>`;
            });

            document.getElementById('viewPartiesModal').style.display = 'flex';
        }

        function openTrashModal() {
            fetch('/api/get-deleted-parties', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => res.json())
            .then(deletedParties => {
                var tbody = document.getElementById('trashPartiesBody');
                tbody.innerHTML = '';

                if(deletedParties.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;">Trash Bin is Empty.</td></tr>';
                } else {
                    deletedParties.forEach(p => {
                        tbody.innerHTML += `<tr>
                            <td><b>${p.party_name}</b></td>
                            <td>${p.deleted_at}</td>
                            <td><button class="btn btn-add" onclick="restoreParty('${p.party_name}')">🔄 Restore Party</button></td>
                        </tr>`;
                    });
                }
                document.getElementById('trashModal').style.display = 'flex';
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
                document.getElementById('modalTitle').innerText = '➕ CREATE New Party Master';
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
                    document.getElementById('modalTitle').innerText = '🔍 DISPLAY Party Master Details';
                    pName.disabled = true; pGst.disabled = true; pGstin.disabled = true;
                    pMob.disabled = true; pCity.disabled = true; pAddr.disabled = true;
                    btn.style.display = 'none';
                } else if(mode === 'ALTER') {
                    document.getElementById('modalTitle').innerText = '✏️ ALTER Party Master Details';
                    pName.disabled = false; pGst.disabled = false; pGstin.disabled = false;
                    pMob.disabled = false; pCity.disabled = false; pAddr.disabled = false;
                    btn.style.display = 'block';
                    btn.innerText = '💾 Update Altered Details';
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
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                closeModal('partyModal');
                fetchPartyMastersList();
            });
        }

        function deletePartySoft(partyName) {
            if(!confirm(`Are you sure you want to delete '${partyName}'? (It will be kept in Trash for 30 Days)`)) return;

            fetch('/api/delete-party-soft', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify({ party_name: partyName })
            })
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                closeModal('viewPartiesModal');
                fetchPartyMastersList();
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
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                closeModal('trashModal');
                fetchPartyMastersList();
            });
        }

        function submitSalesOrder() {
            var state = document.getElementById('ordState').value;
            var city = document.getElementById('ordCity').value;
            var party = document.getElementById('ordParty').value;

            if(!party) return alert('Please select a Party!');

            var items = [];
            var container = document.getElementById('orderItemsContainer');
            var rows = container.querySelectorAll('.row');

            rows.forEach(r => {
                var itemSelect = r.querySelector('.row-item-select').value;
                var rate = parseFloat(r.querySelector('.row-item-rate').value || 0);
                var qty = parseFloat(r.querySelector('.row-item-qty').value || 0);
                var total = rate * qty;

                if(itemSelect && rate > 0 && qty > 0) {
                    items.push({ item_name: itemSelect, rate: rate, qty: qty, total: total });
                }
            });

            if(items.length === 0) return alert('Please add at least 1 valid Item with Rate & Qty!');

            var grandTotal = parseFloat(document.getElementById('grandOrderTotal').innerText || 0);
            var pObj = masterPartiesList.find(p => p.party_name === party);
            var gstStatus = pObj ? pObj.gst_status : 'URD';

            fetch('/api/create-order-multi', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'x-access-token': authToken 
                },
                body: JSON.stringify({ state: state, city: city, party_name: party, gst_status: gstStatus, items: items, grand_total: grandTotal })
            })
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                fetchOrders();
                fetchItemMastersList();
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
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                fetchPartyMastersList();
                fetchItemMastersList();
            });
        }

        function fetchOrders() {
            fetch('/api/get-orders', {
                headers: { 'x-access-token': authToken }
            })
            .then(res => res.json())
            .then(orders => {
                var tbody = document.getElementById('ordersAuditBody');
                tbody.innerHTML = '';
                if(!orders || orders.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">No orders found.</td></tr>';
                    return;
                }
                orders.forEach(o => {
                    var itemsDetail = '';
                    if(o.items && o.items.length > 0) {
                        o.items.forEach(i => {
                            itemsDetail += `• ${i.item_name} (₹${i.rate} x ${i.qty} = ₹${i.total})<br>`;
                        });
                    }

                    tbody.innerHTML += `<tr>
                        <td><b>${o.order_no}</b></td>
                        <td>${o.date}</td>
                        <td>${o.party_name} <br><small>(${o.gst_status})</small></td>
                        <td>${o.city_village}</td>
                        <td><small>${itemsDetail}</small></td>
                        <td><b>${o.salesman_id}</b></td>
                        <td><b style="color:#166534;">₹${o.grand_total}</b></td>
                    </tr>`;
                });
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

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    u_id = data.get('user_id', '').strip()
    pwd = data.get('password', '')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT company_code, user_id, full_name, role, status FROM users WHERE LOWER(user_id) = LOWER(?) AND password = ?', (u_id, pwd))
    user = cursor.fetchone()
    conn.close()

    if user:
        if user[4] != 'Active':
            return jsonify({"status": "error", "message": f"🚫 Account Restricted! Status: '{user[4]}'."}), 403

        token = jwt.encode({
            'company_code': user[0],
            'user_id': user[1],
            'role': user[3],
            'exp': datetime.now(timezone.utc) + timedelta(days=30)
        }, app.config['SECRET_KEY'], algorithm="HS256")

        return jsonify({
            "status": "success",
            "token": token,
            "company_code": user[0],
            "user_id": user[1],
            "full_name": user[2],
            "role": user[3]
        })
    else:
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

    return jsonify({"status": "success", "message": f"🗑️ Party '{p_name}' Moved to Trash Bin! (30 Days Expiry)"})

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
        return jsonify({"status": "success", "message": "🎉 Tally XML Parsed & Auto-Saved to Database!"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"XML Parsing Error: {str(e)}"}), 500

@app.route('/api/create-order-multi', methods=['POST'])
@token_required
def create_order_multi(current_user, current_role, company_code):
    data = request.json
    ord_no = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    ord_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    import json
    items_json_str = json.dumps(data.get('items', []))

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO orders (company_code, order_no, order_date, salesman_id, party_name, gst_status, assigned_state, city_village, items_json, grand_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (company_code, ord_no, ord_date, current_user, data.get('party_name'), data.get('gst_status'), data.get('state'), data.get('city'), items_json_str, data.get('grand_total')))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": f"🎉 Multi-Item Order '{ord_no}' Placed Successfully!"})

@app.route('/api/get-orders')
@token_required
def get_orders(current_user, current_role, company_code):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if current_role == 'ADMIN':
        cursor.execute('SELECT order_no, order_date, party_name, gst_status, city_village, items_json, salesman_id, grand_total FROM orders WHERE company_code = ? ORDER BY id DESC', (company_code,))
    else:
        cursor.execute('SELECT order_no, order_date, party_name, gst_status, city_village, items_json, salesman_id, grand_total FROM orders WHERE company_code = ? AND salesman_id = ? ORDER BY id DESC', (company_code, current_user))

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
            "grand_total": r[7]
        })

    conn.close()
    return jsonify(rows)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)