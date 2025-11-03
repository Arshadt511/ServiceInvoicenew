#!/usr/bin/env python3
"""
A simple vehicle servicing invoicing system implemented using Python's built‑in
HTTP server and SQLite database. The goal is to provide a lightweight,
zero‑dependency solution that a user can run locally to manage customers,
vehicles, bookings and invoices from any modern web browser. This script
creates all necessary database tables on first run, seeds a few example
services and the company details, and serves HTML pages with forms for
creating bookings and viewing invoices.

Key features implemented:
  * Dashboard listing the number of bookings and invoices along with
    shortcuts for adding a new booking and viewing all invoices.
  * Booking form that captures customer and vehicle information as well
    as quantities for pre‑defined services.
  * Automatic invoice generation upon booking submission, with unique
    invoice numbers and calculated totals (exclusive of VAT, VAT and
    inclusive total).
  * Printable invoice pages styled for A4 portrait printing. Users can
    click the "Print Invoice" button in their browser to generate a PDF
    using the browser's built‑in print dialog.

This server intentionally avoids external Python dependencies (no Flask
or Django) to ensure it runs in constrained environments. It should be
started with `python3 run_server.py`. By default it listens on
localhost:8000. You can change the port by setting the PORT environment
variable when running the script.

Note: This implementation is deliberately kept simple. In a real world
application you might want to add authentication, better error handling,
client side validation and a more sophisticated UI framework.
"""

import os
import sqlite3
import datetime
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from string import Template

# Path to the directory containing this script
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT_DIR, "database.db")


def init_db():
    """Create database tables and seed default data if they do not exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create tables
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            address TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            vrm TEXT NOT NULL,
            make TEXT,
            model TEXT,
            mileage INTEGER,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            unit_price REAL NOT NULL,
            vat_rate REAL NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            vehicle_id INTEGER NOT NULL,
            booking_date TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'booked',
            FOREIGN KEY (customer_id) REFERENCES customers(id),
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS booking_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            vat_rate REAL NOT NULL,
            FOREIGN KEY (booking_id) REFERENCES bookings(id),
            FOREIGN KEY (service_id) REFERENCES services(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            invoice_number TEXT NOT NULL,
            issue_date TEXT NOT NULL,
            total_ex_vat REAL NOT NULL,
            total_vat REAL NOT NULL,
            total_inc REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'unpaid',
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );
        """
    )

    # Table for miscellaneous parts/items associated with a booking. These allow
    # custom parts to be priced separately from standard services. Each row
    # records the part name, quantity, unit price and VAT rate.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS misc_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            vat_rate REAL NOT NULL,
            FOREIGN KEY (booking_id) REFERENCES bookings(id)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )

    # Seed default company information if not present
    cur.execute("SELECT COUNT(*) FROM settings")
    count = cur.fetchone()[0]
    if count == 0:
        # Default values for company details, payment info and terms
        default_settings = {
            'company_name': 'Motorhouse Beds Ltd',
            'address_line1': '87 High Street',
            'address_line2': 'Clapham',
            'address_city': 'Bedford',
            'address_county': 'Bedfordshire',
            'address_postcode': 'MK41 6AQ',
            'phone1': '01234 225570',
            'phone2': '07923 829234',
            'email': 'info@motorhouse-beds.co.uk',
            'company_number': '14696224',
            'fca_number': '1000208',
            # Payment methods: comma separated list shown on invoices
            'payment_methods': 'Bank transfer, Credit/Debit card, Cash',
            # Bank details shown on invoices
            'bank_details': 'Sort Code: 01-02-03, Account No: 12345678',
            # Default payment terms (due date offset in days)
            'payment_terms_days': '14',
            # Terms and conditions to show on invoices
            'terms_conditions': 'Payment is due within 14 days of the invoice date. Late payments may incur interest at 2% per month. All goods remain the property of Motorhouse Beds Ltd until paid for in full.'
        }
        cur.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?)",
            list(default_settings.items())
        )

    # Seed default services if table empty
    cur.execute("SELECT COUNT(*) FROM services")
    svc_count = cur.fetchone()[0]
    if svc_count == 0:
        services = [
            ('Full Service', 'Comprehensive vehicle servicing including oil and filter change, safety checks and diagnostics', 200.0, 0.20),
            ('Interim Service', 'Basic service including oil and filter change and essential safety checks', 120.0, 0.20),
            ('MOT Test', 'Annual Ministry of Transport test to ensure roadworthiness', 54.85, 0.00),
            ('Brake Pads Replacement', 'Replace front or rear brake pads as needed', 150.0, 0.20),
            ('Diagnostics', 'Computer diagnostics and fault code reading', 60.0, 0.20)
        ]
        cur.executemany(
            "INSERT INTO services(name, description, unit_price, vat_rate) VALUES (?, ?, ?, ?)",
            services
        )

    conn.commit()
    conn.close()


def get_settings():
    """Return a dictionary of settings from the database."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    return settings


def next_invoice_number():
    """Generate a new invoice number based on the latest invoice ID and current date."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM invoices ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    next_id = (row[0] + 1) if row else 1
    conn.close()
    date_str = datetime.date.today().strftime('%Y%m%d')
    return f"INV{date_str}-{next_id:03d}"


class ServiceRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler implementing a simple routing mechanism."""

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        if path == '/':
            self.handle_dashboard()
        elif path == '/booking/new':
            self.handle_new_booking_form()
        elif path == '/invoices':
            self.handle_invoice_list()
        elif path == '/bookings':
            self.handle_booking_list()
        elif path.startswith('/invoice/'):
            try:
                invoice_id = int(path.split('/')[-1])
                self.handle_invoice(invoice_id)
            except ValueError:
                self.send_error(404, 'Invoice not found')
        elif path.startswith('/static/'):
            self.serve_static(path)
        else:
            self.send_error(404, 'Page not found')

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        fields = urllib.parse.parse_qs(post_data.decode())
        if path == '/booking/new':
            self.process_new_booking(fields)
        elif path == '/booking/cancel':
            self.process_cancel_booking(fields)
        else:
            self.send_error(404, 'Page not found')

    def serve_static(self, path):
        """Serve static files such as CSS."""
        static_path = os.path.join(ROOT_DIR, path.lstrip('/'))
        if os.path.isfile(static_path):
            if static_path.endswith('.css'):
                mime = 'text/css'
            elif static_path.endswith('.js'):
                mime = 'application/javascript'
            else:
                mime = 'application/octet-stream'
            with open(static_path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, 'File not found')

    def render_template(self, template_name, **context):
        """Render an HTML template with the given context variables."""
        template_path = os.path.join(ROOT_DIR, 'templates', template_name)
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        template = Template(template_content)
        # Replace placeholders using template substitute. Any missing variable
        # remains unchanged (safe_substitute). Convert None to empty string.
        safe_context = {k: ('' if v is None else v) for k, v in context.items()}
        return template.safe_substitute(safe_context)

    def handle_dashboard(self):
        """Display the dashboard with counts and actions."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bookings")
        booking_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM invoices")
        invoice_count = cur.fetchone()[0]
        conn.close()
        settings = get_settings()
        html = self.render_template(
            'dashboard.html',
            booking_count=booking_count,
            invoice_count=invoice_count,
            company_name=settings.get('company_name')
        )
        self.respond_html(html)

    def handle_new_booking_form(self):
        """Render the booking form with dynamic list of services."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name, description, unit_price, vat_rate FROM services")
        services = cur.fetchall()
        conn.close()
        # Build HTML for service rows
        service_rows = ''
        for svc in services:
            svc_id, name, description, price, vat = svc
            row = f'''<tr>
                <td>{name}<br><small>{description}</small></td>
                <td>£{price:.2f}</td>
                <td>{int(vat * 100)}%</td>
                <td><input type="number" name="qty_{svc_id}" min="0" max="10" value="0" style="width:60px"></td>
            </tr>'''
            service_rows += row
        html = self.render_template('booking_form.html', services_rows=service_rows)
        self.respond_html(html)

    def process_new_booking(self, fields):
        """Handle POST submission for new booking and create associated records."""
        # Extract customer fields
        first_name = fields.get('first_name', [''])[0].strip()
        last_name = fields.get('last_name', [''])[0].strip()
        phone = fields.get('phone', [''])[0].strip()
        email = fields.get('email', [''])[0].strip()
        address = fields.get('address', [''])[0].strip()
        # Vehicle fields
        vrm = fields.get('vrm', [''])[0].strip().upper()
        make = fields.get('make', [''])[0].strip()
        model = fields.get('model', [''])[0].strip()
        mileage = fields.get('mileage', ['0'])[0].strip()
        # Booking date: allow custom date if provided, else default to today
        date_str = fields.get('booking_date', [''])[0].strip()
        if date_str:
            # Use provided date; validate format (YYYY-MM-DD)
            try:
                datetime.datetime.strptime(date_str, '%Y-%m-%d')
                booking_date = date_str
            except ValueError:
                booking_date = datetime.date.today().isoformat()
        else:
            booking_date = datetime.date.today().isoformat()
        notes = fields.get('notes', [''])[0].strip()

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Insert customer
        cur.execute(
            "INSERT INTO customers(first_name, last_name, phone, email, address) VALUES (?,?,?,?,?)",
            (first_name, last_name, phone, email, address)
        )
        customer_id = cur.lastrowid
        # Insert vehicle
        cur.execute(
            "INSERT INTO vehicles(customer_id, vrm, make, model, mileage) VALUES (?,?,?,?,?)",
            (customer_id, vrm, make, model, int(mileage) if mileage.isdigit() else None)
        )
        vehicle_id = cur.lastrowid
        # Insert booking
        cur.execute(
            "INSERT INTO bookings(customer_id, vehicle_id, booking_date, notes, status) VALUES (?,?,?,?,?)",
            (customer_id, vehicle_id, booking_date, notes, 'booked')
        )
        booking_id = cur.lastrowid
        # Insert booking items and compute totals
        total_ex_vat = 0.0
        total_vat = 0.0
        cur.execute("SELECT id, unit_price, vat_rate FROM services")
        services = cur.fetchall()
        for svc_id, unit_price, vat_rate in services:
            qty_key = f'qty_{svc_id}'
            qty_str = fields.get(qty_key, ['0'])[0]
            try:
                qty = int(qty_str)
            except ValueError:
                qty = 0
            if qty > 0:
                cur.execute(
                    "INSERT INTO booking_items(booking_id, service_id, quantity, unit_price, vat_rate) VALUES (?,?,?,?,?)",
                    (booking_id, svc_id, qty, unit_price, vat_rate)
                )
                line_total = qty * unit_price
                line_vat = line_total * vat_rate
                total_ex_vat += line_total
                total_vat += line_vat
        # Handle up to three miscellaneous parts (custom items)
        for i in range(1, 4):
            name_key = f'custom_name_{i}'
            qty_key = f'custom_qty_{i}'
            price_key = f'custom_price_{i}'
            vat_key = f'custom_vat_{i}'
            name_val = fields.get(name_key, [''])[0].strip()
            qty_val = fields.get(qty_key, ['0'])[0]
            price_val = fields.get(price_key, [''])[0]
            vat_val = fields.get(vat_key, [''])[0]
            # Skip if no name
            if not name_val:
                continue
            try:
                qty_int = int(qty_val)
            except ValueError:
                qty_int = 0
            try:
                price_float = float(price_val)
            except ValueError:
                price_float = 0.0
            try:
                vat_float = float(vat_val)
            except ValueError:
                vat_float = 0.20  # default 20% VAT
            if qty_int > 0 and price_float > 0:
                cur.execute(
                    "INSERT INTO misc_items(booking_id, name, quantity, unit_price, vat_rate) VALUES (?,?,?,?,?)",
                    (booking_id, name_val, qty_int, price_float, vat_float)
                )
                line_total = qty_int * price_float
                line_vat = line_total * vat_float
                total_ex_vat += line_total
                total_vat += line_vat
        # Create invoice record
        if total_ex_vat > 0:
            invoice_number = next_invoice_number()
            total_inc = total_ex_vat + total_vat
            issue_date = datetime.date.today().isoformat()
            cur.execute(
                "INSERT INTO invoices(booking_id, invoice_number, issue_date, total_ex_vat, total_vat, total_inc, status) VALUES (?,?,?,?,?,?,?)",
                (booking_id, invoice_number, issue_date, total_ex_vat, total_vat, total_inc, 'unpaid')
            )
            invoice_id = cur.lastrowid
        else:
            invoice_id = None
        conn.commit()
        conn.close()
        # Redirect to invoice page or dashboard
        if invoice_id:
            self.send_response(303)
            self.send_header('Location', f'/invoice/{invoice_id}')
            self.end_headers()
        else:
            self.send_response(303)
            self.send_header('Location', '/')
            self.end_headers()

    def handle_invoice(self, invoice_id: int):
        """Render a single invoice by ID."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Fetch invoice
        cur.execute(
            "SELECT i.invoice_number, i.issue_date, i.total_ex_vat, i.total_vat, i.total_inc, i.status, b.id, b.booking_date, c.first_name, c.last_name, c.phone, c.email, c.address, v.vrm, v.make, v.model, v.mileage\n"
            "FROM invoices i\n"
            "JOIN bookings b ON i.booking_id = b.id\n"
            "JOIN customers c ON b.customer_id = c.id\n"
            "JOIN vehicles v ON b.vehicle_id = v.id\n"
            "WHERE i.id = ?",
            (invoice_id,)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            self.send_error(404, 'Invoice not found')
            return
        (
            inv_number, issue_date, total_ex, total_vat, total_inc, inv_status,
            booking_id, booking_date, cust_first, cust_last, cust_phone,
            cust_email, cust_address, vrm, make, model, mileage
        ) = row
        # Fetch booking items with service details
        cur.execute(
            "SELECT s.name, s.description, bi.quantity, bi.unit_price, bi.vat_rate\n"
            "FROM booking_items bi\n"
            "JOIN services s ON bi.service_id = s.id\n"
            "WHERE bi.booking_id = ?",
            (booking_id,)
        )
        items = cur.fetchall()
        # Fetch misc (custom) items
        cur.execute(
            "SELECT name, '', quantity, unit_price, vat_rate FROM misc_items WHERE booking_id = ?",
            (booking_id,)
        )
        misc = cur.fetchall()
        # Append misc items to items list. They will have empty description.
        items += misc
        conn.close()
        # Build HTML table rows and collect service names
        item_rows = ''
        service_names = []
        for name, desc, qty, unit_price, vat_rate in items:
            service_names.append(name)
            line_total_ex = qty * unit_price
            line_vat = line_total_ex * vat_rate
            line_total_inc = line_total_ex + line_vat
            item_rows += f'''<tr>
                <td>{name}</td>
                <td>{qty}</td>
                <td>£{unit_price:.2f}</td>
                <td>£{line_total_ex:.2f}</td>
                <td>£{line_vat:.2f}</td>
                <td>£{line_total_inc:.2f}</td>
            </tr>'''
        # Company settings
        settings = get_settings()
        # Compute due date based on payment terms (default 14 days)
        try:
            days = int(settings.get('payment_terms_days', '14'))
        except ValueError:
            days = 14
        issue_dt = datetime.datetime.strptime(issue_date, '%Y-%m-%d')
        due_dt = issue_dt + datetime.timedelta(days=days)
        due_date = due_dt.strftime('%Y-%m-%d')
        # Compute next service due date (simple heuristic: 6 months if Interim Service, else 12 months)
        months = 12
        for name in service_names:
            lower = name.lower()
            if 'interim' in lower:
                months = 6
                break
        next_service_dt = issue_dt + datetime.timedelta(days=30 * months)
        next_service_date = next_service_dt.strftime('%Y-%m-%d')
        # Prepare HTML
        html = self.render_template(
            'invoice.html',
            company_name=settings.get('company_name'),
            address_line1=settings.get('address_line1'),
            address_line2=settings.get('address_line2'),
            address_city=settings.get('address_city'),
            address_county=settings.get('address_county'),
            address_postcode=settings.get('address_postcode'),
            phone1=settings.get('phone1'),
            phone2=settings.get('phone2'),
            email=settings.get('email'),
            company_number=settings.get('company_number'),
            fca_number=settings.get('fca_number'),
            payment_methods=settings.get('payment_methods'),
            bank_details=settings.get('bank_details'),
            terms_conditions=settings.get('terms_conditions'),
            invoice_number=inv_number,
            issue_date=issue_date,
            due_date=due_date,
            next_service_date=next_service_date,
            customer_name=f"{cust_first} {cust_last}",
            customer_phone=cust_phone,
            customer_email=cust_email,
            customer_address=cust_address,
            vehicle_vrm=vrm,
            vehicle_make=make,
            vehicle_model=model,
            vehicle_mileage=(mileage or ''),
            items_rows=item_rows,
            total_ex=f"£{total_ex:.2f}",
            total_vat=f"£{total_vat:.2f}",
            total_inc=f"£{total_inc:.2f}"
        )
        self.respond_html(html)

    def handle_invoice_list(self):
        """Display a list of invoices with basic details."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Fetch invoices joined with customers and bookings
        cur.execute(
            """
            SELECT i.id, i.invoice_number, i.issue_date, i.total_inc, i.status, c.first_name, c.last_name
            FROM invoices i
            JOIN bookings b ON i.booking_id = b.id
            JOIN customers c ON b.customer_id = c.id
            ORDER BY i.issue_date DESC, i.id DESC
            """
        )
        rows = cur.fetchall()
        conn.close()
        # Build table rows
        invoice_rows = ''
        for inv_id, inv_num, issue_date, total_inc, status, first_name, last_name in rows:
            customer_name = f"{first_name} {last_name}".strip()
            invoice_rows += f'''<tr>
                <td><a href="/invoice/{inv_id}">{inv_num}</a></td>
                <td>{issue_date}</td>
                <td>{customer_name}</td>
                <td>£{total_inc:.2f}</td>
                <td>{status}</td>
            </tr>'''
        # Render template
        html = self.render_template('invoice_list.html', invoice_rows=invoice_rows)
        self.respond_html(html)

    def handle_booking_list(self):
        """Display all bookings with status and actions."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Retrieve bookings with customer and vehicle info and invoice details
        cur.execute(
            """
            SELECT b.id, b.booking_date, b.status, c.first_name, c.last_name, v.vrm,
                   IFNULL(i.invoice_number, '') AS invoice_number, i.id AS invoice_id
            FROM bookings b
            JOIN customers c ON b.customer_id = c.id
            JOIN vehicles v ON b.vehicle_id = v.id
            LEFT JOIN invoices i ON i.booking_id = b.id
            ORDER BY b.booking_date DESC, b.id DESC
            """
        )
        rows = cur.fetchall()
        conn.close()
        booking_rows = ''
        for b_id, b_date, status, first_name, last_name, vrm, inv_num, inv_id in rows:
            customer_name = f"{first_name} {last_name}".strip()
            # Cancel action if booking is not canceled
            action_html = ''
            if status != 'canceled':
                action_html = f'''<form method="post" action="/booking/cancel" style="display:inline;"><input type="hidden" name="booking_id" value="{b_id}"><button type="submit" class="btn" onclick="return confirm('Are you sure you want to cancel this booking?');">Cancel</button></form>'''
            # Link to invoice if exists
            inv_link = f'<a href="/invoice/{inv_id}">{inv_num}</a>' if inv_id else ''
            booking_rows += f'''<tr>
                <td>{b_id}</td>
                <td>{b_date}</td>
                <td>{customer_name}</td>
                <td>{vrm}</td>
                <td>{status}</td>
                <td>{inv_link}</td>
                <td>{action_html}</td>
            </tr>'''
        html = self.render_template('booking_list.html', booking_rows=booking_rows)
        self.respond_html(html)

    def process_cancel_booking(self, fields):
        """Cancel a booking and update its invoice status."""
        booking_id_str = fields.get('booking_id', [''])[0]
        try:
            booking_id = int(booking_id_str)
        except ValueError:
            self.send_error(400, 'Invalid booking ID')
            return
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Update booking status
        cur.execute("UPDATE bookings SET status = 'canceled' WHERE id = ?", (booking_id,))
        # Update associated invoice status if exists
        cur.execute("UPDATE invoices SET status = 'canceled' WHERE booking_id = ?", (booking_id,))
        conn.commit()
        conn.close()
        # Redirect back to bookings page
        self.send_response(303)
        self.send_header('Location', '/bookings')
        self.end_headers()

    def respond_html(self, html: str):
        """Send an HTML response to the client."""
        encoded = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(encoded))
        self.end_headers()
        self.wfile.write(encoded)


def run_server():
    init_db()
    port = int(os.environ.get('PORT', 8000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, ServiceRequestHandler)
    print(f"Starting service invoice server on http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == '__main__':
    run_server()