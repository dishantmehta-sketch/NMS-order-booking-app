import os
import re
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, Response

app = Flask(__name__)

XML_FILE_PATH = "Master.xml"
DB_FILE = "orders.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT,
            party_name TEXT,
            party_mobile TEXT,
            total_amount REAL,
            order_date TEXT,
            status TEXT DEFAULT 'Pending'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            item_name TEXT,
            quantity REAL,
            rate REAL,
            amount REAL,
            FOREIGN KEY (order_id) REFERENCES orders (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

LOCAL_DATABASE = {
    "parties": [],
    "stock_items": []
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Standalone ERP Order Portal</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #f4f6f9; margin: 0; padding: 15px; }
        .header { background: #1b4332; color: white; padding: 15px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; }
        .card { background: white; padding: 20px; margin-top: 15px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .form-group { margin-bottom: 15px; }
        label { font-weight: bold; display: block; margin-bottom: 5px; color: #333; }
        select, input { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; font-size: 14px; }
        .row { display: flex; gap: 10px; flex-wrap: wrap; }
        .col { flex: 1; min-width: 140px; }
        .total-box { background: #e8f5e9; padding: 12px; border-radius: 5px; font-weight: bold; color: #2e7d32; font-size: 18px; margin-top: 15px; text-align: right; }
        .party-info { background: #e0f2fe; border: 1px solid #bae6fd; padding: 12px; border-radius: 5px; margin-top: 8px; font-size: 13px; color: #0369a1; display: none; line-height: 1.5; }
        .btn { background-color: #2d6a4f; color: white; padding: 12px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 15px; font-weight: bold; width: 100%; margin-top: 10px; }
        .btn-add { background-color: #2563eb; width: auto; padding: 10px 20px; margin-top: 0; }
        .btn-sync { background-color: #0284c7; }
        .btn-danger { background-color: #ef4444; padding: 6px 10px; font-size: 12px; border-radius: 4px; border:none; color:white; cursor:pointer; font-weight:bold; }
        .btn-action { padding: 6px 10px; font-size: 12px; border-radius: 4px; border:none; color:white; cursor:pointer; font-weight:bold; text-decoration:none; display:inline-block; margin-right:4px; margin-bottom: 4px; }
        .btn-print { background-color: #0d9488; }
        .btn-export { background-color: #d97706; }
        .btn-wa { background-color: #25D366; color: white; }
        .status { padding: 10px; background: #d8f3dc; color: #1b4332; border-radius: 5px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 13px; }
        th { background-color: #2d6a4f; color: white; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .item-box { background: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 6px; margin-top: 10px; }
        .table-responsive { overflow-x: auto; }
    </style>
</head>
<body>
    <div class="header">
        <h2>📊 Smart ERP Order Booking Portal</h2>
        <span>Status: <b>Active</b></span>
    </div>
    <div class="card">
        <div class="status">
            <span id="syncStatus">💡 Master.xml se data import karne ke liye click karein</span>
            <button class="btn btn-sync" style="width: auto; margin:0;" onclick="loadFromXMLFile()">📁 Import Master Data</button>
        </div>
    </div>
    <div class="card">
        <h3>📦 Create Order Booking Voucher</h3>
        <div class="form-group">
            <label>Select Customer / Party Name:</label>
            <select id="partySelect" onchange="showPartyDetails()">
                <option value="">-- Select Customer Party --</option>
            </select>
            <div id="partyDetails" class="party-info"></div>
        </div>
        <div class="form-group">
            <label>Customer Mobile Number (For WhatsApp Bill):</label>
            <input type="tel" id="partyMobile" placeholder="10-digit mobile number enter/update karein">
        </div>
        <hr style="border:0; border-top:1px solid #e2e8f0; margin: 20px 0;">
        <div class="item-box">
            <h4 style="margin-top:0; color:#1e293b;">🛒 Add Items to Order Basket</h4>
            <div class="row">
                <div class="col" style="flex:2;">
                    <label>Select Stock Item:</label>
                    <select id="itemSelect">
                        <option value="">-- Select Stock Item --</option>
                    </select>
                </div>
                <div class="col">
                    <label>Qty:</label>
                    <input type="number" id="qty" placeholder="Qty">
                </div>
                <div class="col">
                    <label>Rate (₹):</label>
                    <input type="number" id="rate" placeholder="Rate" step="0.01">
                </div>
                <div class="col" style="display:flex; align-items:flex-end;">
                    <button type="button" class="btn btn-add" onclick="addItemToBasket()">➕ Add Item</button>
                </div>
            </div>
        </div>
        <h4 style="margin-bottom:5px;">📋 Selected Items List</h4>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>S.No</th>
                        <th>Item Name</th>
                        <th>Qty</th>
                        <th>Rate (₹)</th>
                        <th>Amount (₹)</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="basketTableBody">
                    <tr><td colspan="6" style="text-align:center; color:#888;">Koi item add nahi kiya gaya hai.</td></tr>
                </tbody>
            </table>
        </div>
        <div class="total-box">
            Grand Total Amount: ₹ <span id="grandTotal">0.00</span>
        </div>
        <button type="button" class="btn" onclick="saveCompleteOrder()" style="margin-top:20px; font-size:16px;">💾 Save Order Booking Voucher</button>
    </div>
    <div class="card">
        <h3>📑 Saved Booking Orders History</h3>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Booking Order No</th>
                        <th>Date</th>
                        <th>Party Name</th>
                        <th>Items Ordered</th>
                        <th>Grand Total (₹)</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="ordersTableBody">
                    <tr><td colspan="6" style="text-align:center;">No orders saved yet.</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    <script>
        var fullPartyData = [];
        var currentBasket = [];

        function loadMasters() {
            fetch('/get-local-masters')
                .then(function(res) { return res.json(); })
                .then(function(data) {
                    fullPartyData = data.parties;
                    var partySelect = document.getElementById('partySelect');
                    partySelect.innerHTML = '<option value="">-- Select Customer Party --</option>';
                    data.parties.forEach(function(p) {
                        var opt = document.createElement('option');
                        opt.value = p.name;
                        opt.innerText = p.name;
                        partySelect.appendChild(opt);
                    });

                    var itemSelect = document.getElementById('itemSelect');
                    itemSelect.innerHTML = '<option value="">-- Select Stock Item --</option>';
                    data.stock_items.forEach(function(item) {
                        var opt = document.createElement('option');
                        opt.value = item;
                        opt.innerText = item;
                        itemSelect.appendChild(opt);
                    });
                });
        }

        function showPartyDetails() {
            var partyName = document.getElementById('partySelect').value;
            var infoBox = document.getElementById('partyDetails');
            var mobInput = document.getElementById('partyMobile');
            var p = null;
            for(var i=0; i<fullPartyData.length; i++) {
                if(fullPartyData[i].name === partyName) {
                    p = fullPartyData[i];
                    break;
                }
            }
            
            if(p) {
                infoBox.style.display = 'block';
                infoBox.innerHTML = '📍 <b>Address:</b> ' + (p.address || 'N/A') + '<br>🆔 <b>GSTIN/UIN:</b> ' + (p.gst || 'N/A');
                mobInput.value = p.mobile || '';
            } else {
                infoBox.style.display = 'none';
                mobInput.value = '';
            }
        }

        function loadFromXMLFile() {
            document.getElementById('syncStatus').innerText = "⏳ Data load ho raha hai, wait karein...";
            fetch('/import-xml')
                .then(function(res) { return res.json(); })
                .then(function(res) {
                    alert(res.message);
                    document.getElementById('syncStatus').innerText = "✅ Total " + res.parties_count + " Parties & " + res.items_count + " Items loaded successfully!";
                    loadMasters();
                });
        }

        function addItemToBasket() {
            var item = document.getElementById('itemSelect').value;
            var qty = parseFloat(document.getElementById('qty').value) || 0;
            var rate = parseFloat(document.getElementById('rate').value) || 0;

            if(!item || qty <= 0 || rate <= 0) {
                alert('Kripya Item, Valid Quantity aur Rate chunein!');
                return;
            }

            var amount = qty * rate;
            currentBasket.push({ item_name: item, qty: qty, rate: rate, amount: amount });

            document.getElementById('itemSelect').value = '';
            document.getElementById('qty').value = '';
            document.getElementById('rate').value = '';

            renderBasket();
        }

        function removeItemFromBasket(index) {
            currentBasket.splice(index, 1);
            renderBasket();
        }

        function renderBasket() {
            var tbody = document.getElementById('basketTableBody');
            var grandTotal = 0;

            if(currentBasket.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">Koi item add nahi kiya gaya hai.</td></tr>';
                document.getElementById('grandTotal').innerText = '0.00';
                return;
            }

            tbody.innerHTML = '';
            currentBasket.forEach(function(b, idx) {
                grandTotal += b.amount;
                var row = '<tr>' +
                    '<td>' + (idx + 1) + '</td>' +
                    '<td><b>' + b.item_name + '</b></td>' +
                    '<td>' + b.qty + '</td>' +
                    '<td>₹' + b.rate.toFixed(2) + '</td>' +
                    '<td>₹' + b.amount.toFixed(2) + '</td>' +
                    '<td><button class="btn-danger" onclick="removeItemFromBasket(' + idx + ')">🗑️ Delete</button></td>' +
                '</tr>';
                tbody.innerHTML += row;
            });

            document.getElementById('grandTotal').innerText = grandTotal.toFixed(2);
        }

        function saveCompleteOrder() {
            var party = document.getElementById('partySelect').value;
            var mobile = document.getElementById('partyMobile').value.trim();

            if(!party) {
                alert('Kripya pehle Customer Party Select karein!');
                return;
            }

            if(currentBasket.length === 0) {
                alert('Kripya kam se kam ek Item Basket me Add karein!');
                return;
            }

            fetch('/save-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ party_name: party, party_mobile: mobile, items: currentBasket })
            })
            .then(function(res) { return res.json(); })
            .then(function(data) {
                alert(data.message);
                currentBasket = [];
                renderBasket();
                fetchOrders();
            });
        }

        function deleteOrder(orderId, orderNo) {
            if(confirm('Kya aap sach me Order ' + orderNo + ' delete karna chahte hain?')) {
                fetch('/delete-order/' + orderId, { method: 'DELETE' })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        alert(data.message);
                        fetchOrders();
                    });
            }
        }

        function sendWhatsApp(orderNo, party, total, mobile, itemsJsonStr) {
            var targetMobile = mobile;
            if(!targetMobile) {
                targetMobile = prompt("Customer Mobile Number add/change karein:", "");
            }
            if(!targetMobile) {
                alert("Mobile number ke bina WhatsApp nahi bheja ja sakta.");
                return;
            }

            var cleanPhone = targetMobile.replace(/\\D/g, '');
            if(cleanPhone.length === 10) cleanPhone = "91" + cleanPhone;

            var itemsArr = JSON.parse(itemsJsonStr);
            var itemsTextSummary = "";
            for(var i=0; i<itemsArr.length; i++) {
                itemsTextSummary += "• " + itemsArr[i].item + " (x" + itemsArr[i].qty + " @ ₹" + itemsArr[i].rate + ") = ₹" + itemsArr[i].amount + "\\n";
            }

            var msg = "*--- ORDER BOOKING SLIP ---*\\n" +
                      "*Order No:* " + orderNo + "\\n" +
                      "*Customer:* " + party + "\\n" +
                      "*Items Details:*\\n" + itemsTextSummary + "\\n" +
                      "*Total Amount:* ₹" + total.toFixed(2) + "\\n\\n" +
                      "Aapka Order Booking Voucher create ho gaya hai. Dhanyawad!";

            window.open("https://wa.me/" + cleanPhone + "?text=" + encodeURIComponent(msg), '_blank');
        }

        function fetchOrders() {
            fetch('/get-orders')
                .then(function(res) { return res.json(); })
                .then(function(orders) {
                    var tbody = document.getElementById('ordersTableBody');
                    if(orders.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">No orders saved yet.</td></tr>';
                        return;
                    }
                    tbody.innerHTML = '';
                    orders.forEach(function(o) {
                        var itemListHtml = "";
                        for(var j=0; j<o.items.length; j++) {
                            itemListHtml += "• " + o.items[j].item + " (x" + o.items[j].qty + " @ ₹" + o.items[j].rate + ")<br>";
                        }
                        var itemsJsonStr = JSON.stringify(o.items).replace(/"/g, '&quot;');
                        
                        var row = '<tr>' +
                            '<td><b>' + o.order_no + '</b></td>' +
                            '<td>' + o.date + '</td>' +
                            '<td><b>' + o.party + '</b><br><small style="color:#666;">📱 ' + (o.mobile || 'No Mobile') + '</small></td>' +
                            '<td style="font-size:12px; color:#334155;">' + itemListHtml + '</td>' +
                            '<td><b>₹' + o.total.toFixed(2) + '</b></td>' +
                            '<td>' +
                                '<a href="/print-order/' + o.id + '" target="_blank" class="btn-action btn-print">🖨️ Print Slip</a> ' +
                                '<button onclick="sendWhatsApp(\'' + o.order_no + '\', \'' + o.party + '\', ' + o.total + ', \'' + (o.mobile || '') + '\', \'' + itemsJsonStr + '\')" class="btn-action btn-wa">📲 WhatsApp</button> ' +
                                '<a href="/export-tally-xml/' + o.id + '" class="btn-action btn-export">📥 XML</a> ' +
                                '<button onclick="deleteOrder(' + o.id + ', \'' + o.order_no + '\')" class="btn-danger">🗑️ Delete</button>' +
                            '</td>' +
                        '</tr>';
                        tbody.innerHTML += row;
                    });
                });
        }

        loadMasters();
        fetchOrders();
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/get-local-masters')
def get_local_masters():
    return jsonify(LOCAL_DATABASE)

@app.route('/import-xml')
def import_xml():
    if not os.path.exists(XML_FILE_PATH):
        return jsonify({"status": "error", "message": f"'{XML_FILE_PATH}' file nahi mili!"})

    try:
        with open(XML_FILE_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        content = content.replace("&amp;", "&")
        content = re.sub(r'&#[0-9]+;', '', content)

        ledger_blocks = re.findall(r'<LEDGER\b[^>]*>(.*?)</LEDGER>', content, re.DOTALL | re.IGNORECASE)
        parties = []

        for block in ledger_blocks:
            name_match = re.search(r'NAME="([^"]+)"', block) or re.search(r'<NAME[^>]*>(.*?)</NAME>', block)
            if name_match:
                p_name = re.sub(r'<[^>]+>', '', name_match.group(1)).strip()
                if p_name and p_name not in ['Sundry Debtors', 'Sundry Creditors', 'Primary']:
                    addrs = re.findall(r'<ADDRESS[^>]*>(.*?)</ADDRESS>', block)
                    address = ", ".join([re.sub(r'<[^>]+>', '', a).strip() for a in addrs if a.strip()])
                    
                    gst_m = re.search(r'<(?:PARTYGSTIN|GSTIN)[^>]*>(.*?)</(?:PARTYGSTIN|GSTIN)>', block)
                    gst = re.sub(r'<[^>]+>', '', gst_m.group(1)).strip() if gst_m else ""

                    mob_m = re.search(r'<(?:LEDGERPHONE|LEDGERMOBILE)[^>]*>(.*?)</(?:LEDGERPHONE|LEDGERMOBILE)>', block)
                    mob = re.sub(r'<[^>]+>', '', mob_m.group(1)).strip() if mob_m else ""

                    parties.append({"name": p_name, "address": address, "gst": gst, "mobile": mob})

        stock_blocks = re.findall(r'<STOCKITEM\b[^>]*>(.*?)</STOCKITEM>', content, re.DOTALL | re.IGNORECASE)
        items = []
        for block in stock_blocks:
            st_m = re.search(r'NAME="([^"]+)"', block) or re.search(r'<NAME[^>]*>(.*?)</NAME>', block)
            if st_m:
                st_name = re.sub(r'<[^>]+>', '', st_m.group(1)).strip()
                if st_name and st_name not in ['Stock Items', 'Primary']:
                    items.append(st_name)

        unique_parties = list({p['name']: p for p in parties}.values())
        LOCAL_DATABASE['parties'] = sorted(unique_parties, key=lambda x: x['name'])
        LOCAL_DATABASE['stock_items'] = sorted(list(set(items)))

        return jsonify({
            "status": "success",
            "message": f"🎉 {len(LOCAL_DATABASE['parties'])} Parties & {len(LOCAL_DATABASE['stock_items'])} Items loaded!",
            "parties_count": len(LOCAL_DATABASE['parties']),
            "items_count": len(LOCAL_DATABASE['stock_items'])
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/save-order', methods=['POST'])
def save_order():
    data = request.json
    party = data.get('party_name')
    mobile = data.get('party_mobile', '')
    items = data.get('items', [])

    if not party or not items:
        return jsonify({"status": "error", "message": "Data missing!"})

    grand_total = sum(i['amount'] for i in items)
    
    now = datetime.now()
    date_formatted = now.strftime("%d-%B-%Y")
    full_datetime = now.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM orders WHERE order_date LIKE ?", (f"{now.strftime('%Y-%m-%d')}%",))
    today_count = cursor.fetchone()[0] + 1

    order_no = f"ORD|{date_formatted}|{today_count}"

    cursor.execute('''
        INSERT INTO orders (order_no, party_name, party_mobile, total_amount, order_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (order_no, party, mobile, grand_total, full_datetime))
    order_id = cursor.lastrowid

    for item in items:
        cursor.execute('''
            INSERT INTO order_items (order_id, item_name, quantity, rate, amount)
            VALUES (?, ?, ?, ?, ?)
        ''', (order_id, item['item_name'], item['qty'], item['rate'], item['amount']))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": f"🎉 Order {order_no} Saved Successfully!"})

@app.route('/delete-order/<int:order_id>', methods=['DELETE'])
def delete_order(order_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM order_items WHERE order_id = ?', (order_id,))
    cursor.execute('DELETE FROM orders WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": f"🗑️ Order deleted successfully!"})

@app.route('/get-orders')
def get_orders():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, order_no, order_date, party_name, party_mobile, total_amount FROM orders ORDER BY id DESC')
    orders_raw = cursor.fetchall()

    orders = []
    for r in orders_raw:
        order_id = r[0]
        cursor.execute('SELECT item_name, quantity, rate, amount FROM order_items WHERE order_id = ?', (order_id,))
        item_rows = cursor.fetchall()
        items_list = [{"item": it[0], "qty": it[1], "rate": it[2], "amount": it[3]} for it in item_rows]

        orders.append({
            "id": order_id,
            "order_no": r[1],
            "date": r[2],
            "party": r[3],
            "mobile": r[4],
            "total": r[5],
            "items": items_list
        })

    conn.close()
    return jsonify(orders)

@app.route('/print-order/<int:order_id>')
def print_order(order_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, order_no, order_date, party_name, total_amount FROM orders WHERE id = ?', (order_id,))
    o = cursor.fetchone()

    if not o:
        return "Order Not Found!"

    cursor.execute('SELECT item_name, quantity, rate, amount FROM order_items WHERE order_id = ?', (order_id,))
    items_raw = cursor.fetchall()

    items = []
    taxable_val = 0.0
    total_qty = 0.0
    for i in items_raw:
        taxable_val += float(i[3])
        total_qty += float(i[1])
        items.append({
            "item_name": i[0],
            "quantity": f"{float(i[1]):.0f}",
            "rate": f"{float(i[2]):.2f}",
            "amount": f"{float(i[3]):.2f}"
        })

    party_info = next((p for p in LOCAL_DATABASE['parties'] if p['name'] == o[3]), {})
    dt_obj = datetime.strptime(o[2], "%Y-%m-%d %H:%M:%S")
    formatted_date = dt_obj.strftime("%d-%b-%Y")

    conn.close()

    PRINT_TEMPLATE = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Order Booking Invoice - {{ order_no }}</title>
        <style>
            @page { size: A5 portrait; margin: 8mm; }
            body { font-family: Arial, sans-serif; font-size: 9px; margin: 0; padding: 0; background: #fff; }
            .invoice-box { width: 100%; border: 1px solid #000; box-sizing: border-box; }
            .header-title { text-align: center; border-bottom: 1px solid #000; padding: 3px; font-weight: bold; font-size: 11px; text-transform: uppercase; background: #f2f2f2; }
            .top-section { display: table; width: 100%; border-bottom: 1px solid #000; }
            .company-details { display: table-cell; width: 55%; padding: 4px; border-right: 1px solid #000; vertical-align: top; line-height: 1.2; }
            .invoice-meta { display: table-cell; width: 45%; padding: 4px; vertical-align: top; line-height: 1.3; }
            .buyer-section { padding: 4px; border-bottom: 1px solid #000; line-height: 1.2; }
            table.items-table { width: 100%; border-collapse: collapse; }
            table.items-table th, table.items-table td { border-right: 1px solid #000; border-bottom: 1px solid #000; padding: 3px; font-size: 8.5px; text-align: left; }
            table.items-table th { font-weight: bold; text-align: center; background-color: #f2f2f2; }
            .last-col { border-right: none !important; }
            .footer-section { display: table; width: 100%; border-top: 1px solid #000; font-size: 8px; }
            .declaration { display: table-cell; width: 50%; padding: 4px; border-right: 1px solid #000; vertical-align: top; }
            .bank-details { display: table-cell; width: 50%; padding: 4px; text-align: right; vertical-align: top; }
            .no-print { text-align: center; margin-bottom: 10px; }
            @media print { .no-print { display: none; } }
        </style>
    </head>
    <body>
        <div class="no-print">
            <button onclick="window.print()" style="padding: 8px 16px; background: #1b4332; color: white; border: none; font-weight: bold; cursor: pointer; border-radius: 4px;">🖨️ Print Order Booking Invoice (A5 Portrait)</button>
        </div>
        <div class="invoice-box">
            <div class="header-title">Order Booking Invoice</div>
            <div class="top-section">
                <div class="company-details">
                    <b style="font-size:10px;">New Mehta Sales Corporation (2026-27)</b><br>
                    Branch-31 Shahar Saray, Ratlam | Office-T.I.T Road, Ratlam<br>
                    FSSAI No: 11418810000087 | Ph: 8109841762<br>
                    GSTIN/UIN: 23ADBPM8917A1ZY | State: MP, Code: 23
                </div>
                <div class="invoice-meta">
                    <table style="width:100%; border:none; font-size:8.5px;">
                        <tr><td>Order No.</td><td>: <b>{{ order_no }}</b></td></tr>
                        <tr><td>Dated</td><td>: <b>{{ formatted_date }}</b></td></tr>
                        <tr><td>Payment Terms</td><td>: Credit</td></tr>
                    </table>
                </div>
            </div>
            <div class="buyer-section">
                <span style="font-size:7.5px; color:#555;">Buyer Details:</span><br>
                <b style="font-size:9.5px;">{{ party_name }}</b><br>
                {{ party_address if party_address else 'Hat Road, Ratlam' }}<br>
                GSTIN/UIN: <b>{{ party_gst if party_gst else '23ABQPM8143F1ZJ' }}</b>
            </div>
            <table class="items-table">
                <thead>
                    <tr>
                        <th style="width: 5%;">S.N.</th>
                        <th style="width: 45%;">Description</th>
                        <th style="width: 12%;">Qty</th>
                        <th style="width: 15%;">Rate</th>
                        <th class="last-col" style="width: 23%;">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in items %}
                    <tr>
                        <td style="text-align:center;">{{ loop.index }}</td>
                        <td><b>{{ item.item_name }}</b></td>
                        <td style="text-align:center;">{{ item.quantity }} Pcs</td>
                        <td style="text-align:right;">{{ item.rate }}</td>
                        <td class="last-col" style="text-align:right;">{{ item.amount }}</td>
                    </tr>
                    {% endfor %}
                    <tr style="font-weight:bold; background:#fafafa;">
                        <td></td>
                        <td style="text-align:right;">Grand Total</td>
                        <td style="text-align:center;">{{ total_qty }} Pcs</td>
                        <td></td>
                        <td class="last-col" style="text-align:right;">₹ {{ grand_total }}</td>
                    </tr>
                </tbody>
            </table>
            <div style="padding: 3px; font-size:8px; border-bottom: 1px solid #000;">
                Amount Chargeable: <b>INR {{ grand_total }} Only</b>
            </div>
            <div class="footer-section">
                <div class="declaration">
                    <b>Company's PAN: ADBPM8917A</b><br>
                    "This is an Order Booking Voucher. Final Tax Invoice will be generated upon delivery."
                </div>
                <div class="bank-details">
                    <b>New Mehta Sales Corporation</b><br>
                    Bank: <b>YES Bank</b> | A/c: <b>100484600000132</b><br>
                    IFSC: <b>YESB0001004</b><br><br>
                    <span>Authorised Signatory</span>
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    return render_template_string(
        PRINT_TEMPLATE,
        order_no=o[1],
        formatted_date=formatted_date,
        party_name=o[3],
        party_address=party_info.get('address', ''),
        party_gst=party_info.get('gst', ''),
        items=items,
        total_qty=f"{total_qty:.0f}",
        grand_total=f"{taxable_val:.2f}"
    )

@app.route('/export-tally-xml/<int:order_id>')
def export_tally_xml(order_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id, order_no, order_date, party_name, total_amount FROM orders WHERE id = ?', (order_id,))
    o = cursor.fetchone()

    if not o:
        return "Order Not Found!"

    cursor.execute('SELECT item_name, quantity, rate, amount FROM order_items WHERE order_id = ?', (order_id,))
    items_raw = cursor.fetchall()
    conn.close()

    party_name = o[3]
    date_str = datetime.strptime(o[2], "%Y-%m-%d %H:%M:%S").strftime("%Y%m%d")

    xml_items_list = []
    for item in items_raw:
        xml_items_list.append(
            "<ALLINVENTORYENTRIES.LIST>"
            f"<STOCKITEMNAME>{item[0]}</STOCKITEMNAME>"
            "<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>"
            f"<RATE>{item[2]}/Pcs</RATE>"
            f"<AMOUNT>{item[3]}</AMOUNT>"
            f"<ACTUALQTY>{item[1]} Pcs</ACTUALQTY>"
            f"<BILLEDQTY>{item[1]} Pcs</BILLEDQTY>"
            "</ALLINVENTORYENTRIES.LIST>"
        )
    xml_items = "".join(xml_items_list)

    tally_xml = (
        "<ENVELOPE>"
        "<HEADER>"
        "<TALLYREQUEST>Import Data</TALLYREQUEST>"
        "</HEADER>"
        "<BODY>"
        "<IMPORTDATA>"
        "<REQUESTDESC>"
        "<REPORTNAME>Vouchers</REPORTNAME>"
        "</REQUESTDESC>"
        "<REQUESTDATA>"
        '<TALLYMESSAGE xmlns:UDF="TallyUDF">'
        '<VOUCHER VCHTYPE="Sales Order" ACTION="Create">'
        f"<DATE>{date_str}</DATE>"
        f"<PARTYLEDGERNAME>{party_name}</PARTYLEDGERNAME>"
        "<VOUCHERTYPENAME>Sales Order</VOUCHERTYPENAME>"
        f"<VOUCHERNUMBER>{o[1]}</VOUCHERNUMBER>"
        f"{xml_items}"
        "</VOUCHER>"
        "</TALLYMESSAGE>"
        "</REQUESTDATA>"
        "</IMPORTDATA>"
        "</BODY>"
        "</ENVELOPE>"
    )

    return Response(tally_xml, mimetype='text/xml', headers={'Content-Disposition': f'attachment;filename=Order_{order_id}_Tally.xml'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)