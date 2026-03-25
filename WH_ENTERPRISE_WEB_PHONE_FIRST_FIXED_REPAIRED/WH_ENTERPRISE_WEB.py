from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
import textwrap
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "erp.sqlite3"
UPLOAD_DIR = BASE_DIR / "uploads"
PO_DIR = UPLOAD_DIR / "po"
PACKING_DIR = UPLOAD_DIR / "packing_lists"
ATTACH_DIRS = [UPLOAD_DIR, PO_DIR, PACKING_DIR]

for d in ATTACH_DIRS:
    d.mkdir(parents=True, exist_ok=True)

TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
ASSET_DIR = BASE_DIR / "assets" / "images"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

BASE_TEMPLATE = "\n<!doctype html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"utf-8\">\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n  <meta name=\"apple-mobile-web-app-capable\" content=\"yes\">\n  <meta name=\"apple-mobile-web-app-status-bar-style\" content=\"black-translucent\">\n  <meta name=\"apple-mobile-web-app-title\" content=\"Warehouse ERP\">\n  <meta name=\"theme-color\" content=\"#111111\">\n  <link rel=\"manifest\" href=\"/static/manifest.json\">\n  <link rel=\"apple-touch-icon\" href=\"/assets/images/apple-touch-icon.png\">\n  <link rel=\"stylesheet\" href=\"/static/style.css\">\n  <script defer src=\"/static/app.js\"></script>\n  <title>{{ title or \"Warehouse Enterprise ERP\" }}</title>\n</head>\n<body class=\"{{ theme_class }}\" data-path=\"{{ request.url.path if request else '/' }}\">\n  <div class=\"topbar\">\n    <div class=\"brand\">\n      <img src=\"/assets/images/{{ logo_name }}\" alt=\"logo\" class=\"logo-banner\">\n      <div>\n        <div style=\"font-size:1.05rem;\">Warehouse Enterprise ERP</div>\n        <div class=\"small\">{{ user.full_name if user else \"Guest\" }}{% if user %} \u00b7 {{ user.role.replace('_',' ').title() }}{% endif %}</div>\n      </div>\n    </div>\n\n    <div class=\"navlinks desktop-nav\">\n      {% if user %}\n      <a href=\"/\">Dashboard</a>\n      <a href=\"/inventory\">Inventory</a>\n      <a href=\"/requisitions\">Requisitions</a>\n      <a href=\"/purchase-orders\">Purchase Orders</a>\n      <a href=\"/receiving\">Receiving</a>\n      <a href=\"/reports\">Reports</a>\n      {% if user.role == \"admin\" %}<a href=\"/users\">Users</a>{% endif %}\n      {% endif %}\n    </div>\n\n    <div class=\"nav-right\">\n      <form method=\"post\" action=\"/theme\" style=\"display:flex; gap:8px; align-items:center; margin:0;\">\n        <select name=\"theme\" onchange=\"this.form.submit()\" aria-label=\"Theme\">\n          {% for t in themes %}\n          <option value=\"{{ t }}\" {% if t == theme_name %}selected{% endif %}>{{ t }}</option>\n          {% endfor %}\n        </select>\n      </form>\n      {% if user %}\n      <form method=\"post\" action=\"/logout\" style=\"margin:0;\">\n        <button class=\"btn\" type=\"submit\">Logout</button>\n      </form>\n      {% endif %}\n    </div>\n  </div>\n\n  {% if user %}\n  <nav class=\"mobile-nav\" aria-label=\"Mobile navigation\">\n    <a href=\"/\">Home</a>\n    <a href=\"/inventory\">Inventory</a>\n    <a href=\"/requisitions/new\">New Req</a>\n    <a href=\"/purchase-orders\">POs</a>\n    <a href=\"/receiving\">Receive</a>\n    <a href=\"/reports\">Reports</a>\n  </nav>\n  {% endif %}\n\n  <div class=\"container\">\n    {% if message %}\n      <div class=\"flash {{ kind or 'success' }}\">{{ message }}</div>\n    {% endif %}\n    <div class=\"page-grid {% if not user %}no-sidebar{% endif %}\">\n      {% if user %}\n      <aside class=\"sidebar\">\n        <h3>Quick Links</h3>\n        <a href=\"/\">Dashboard</a>\n        <a href=\"/requisitions/new\">New Requisition</a>\n        <a href=\"/inventory\">Add / Issue Inventory</a>\n        <a href=\"/reports\">Usage Reports</a>\n        {% if user.role == 'admin' %}\n        <a href=\"/users\">User Administration</a>\n        {% endif %}\n        <div class=\"notice\" style=\"margin-top:14px;\">\n          <div><strong>System Status</strong></div>\n          <div class=\"small\">Phone-first ERP layout with touch-friendly controls and stand-alone home screen support.</div>\n        </div>\n      </aside>\n      {% endif %}\n      <main class=\"content\">\n        {% block content %}{% endblock %}\n      </main>\n    </div>\n    <div class=\"footer\">Warehouse Enterprise ERP \u00b7 {{ current_year }}</div>\n  </div>\n  <script>\n    if ('serviceWorker' in navigator) {\n      navigator.serviceWorker.register('/static/sw.js').catch(()=>{});\n    }\n  </script>\n</body>\n</html>\n"
LOGIN_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\" style=\"max-width: 560px; margin: 28px auto;\">\n  <h2>Sign in</h2>\n  <p class=\"small\">Use one of the seeded accounts to start, then add your own users under User Administration.</p>\n  <div class=\"notice\">\n    <strong>Phone-first access</strong>\n    <div class=\"small\">Open this ERP in Safari, then use Share \u2192 Add to Home Screen for an app-like launch icon.</div>\n  </div>\n  <form method=\"post\" action=\"/login\" class=\"grid\">\n    <div class=\"form-row two\">\n      <div>\n        <label>Username</label>\n        <input name=\"username\" required placeholder=\"admin\" autocomplete=\"username\">\n      </div>\n      <div>\n        <label>Password</label>\n        <input name=\"password\" type=\"password\" required placeholder=\"admin123\" autocomplete=\"current-password\">\n      </div>\n    </div>\n    <div class=\"form-actions\">\n      <input type=\"submit\" class=\"btn primary\" value=\"Login\">\n    </div>\n  </form>\n  <div class=\"notice\" style=\"margin-top:16px;\">\n    <strong>Seeded accounts:</strong>\n    <div class=\"small\">admin / admin123 \u00b7 requester / requester123 \u00b7 approver / approver123 \u00b7 buyer / buyer123 \u00b7 plant / plant123 \u00b7 receiver / receiver123</div>\n  </div>\n</div>\n{% endblock %}\n"
DASHBOARD_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"grid cols-4\">\n  <div class=\"stat card\"><div class=\"label\">Inventory Items</div><div class=\"value\">{{ stats.total_items }}</div></div>\n  <div class=\"stat card\"><div class=\"label\">Inventory Value</div><div class=\"value\">{{ money(stats.total_value) }}</div></div>\n  <div class=\"stat card\"><div class=\"label\">Open Requisitions</div><div class=\"value\">{{ stats.open_req }}</div></div>\n  <div class=\"stat card\"><div class=\"label\">Received Requisitions</div><div class=\"value\">{{ stats.received }}</div></div>\n</div>\n\n<div class=\"grid cols-2\" style=\"margin-top:18px;\">\n  <div class=\"card\">\n    <h2>Low Stock Alerts</h2>\n    {% if stats.low_stock %}\n      <div class=\"table-wrap\">\n        <table>\n          <thead><tr><th>Part #</th><th>Description</th><th>On Hand</th><th>Min</th><th>Reorder</th></tr></thead>\n          <tbody>\n          {% for item in stats.low_stock %}\n            <tr>\n              <td>{{ item.part_no }}</td>\n              <td>{{ item.description }}</td>\n              <td><span class=\"status {% if item.on_hand <= 0 %}rejected{% else %}partially-received{% endif %}\">{{ item.on_hand }}</span></td>\n              <td>{{ item.min_level }}</td>\n              <td>{{ item.reorder_qty }}</td>\n            </tr>\n          {% endfor %}\n          </tbody>\n        </table>\n      </div>\n    {% else %}\n      <div class=\"notice\">No items are below the minimum level.</div>\n    {% endif %}\n  </div>\n\n  <div class=\"card\">\n    <h2>Pending Requisitions</h2>\n    {% if stats.pending %}\n      <div class=\"timeline\">\n      {% for req in stats.pending %}\n        <div class=\"timeline-item\">\n          <strong><a href=\"/requisitions/{{ req.id }}\">{{ req.req_no }}</a></strong>\n          <div class=\"small\">{{ req.requester }} \u00b7 {{ req.department }}</div>\n          <div><span class=\"status {{ req.status|lower|replace(' ','-') }}\">{{ req.status }}</span></div>\n        </div>\n      {% endfor %}\n      </div>\n    {% else %}\n      <div class=\"notice\">No requisitions waiting right now.</div>\n    {% endif %}\n  </div>\n</div>\n\n<div class=\"grid cols-2\">\n  <div class=\"card\">\n    <h2>Top Items Used</h2>\n    {% if stats.top_items %}\n      {% set max_qty = stats.top_items[0].total_qty or 1 %}\n      {% for item in stats.top_items %}\n        <div style=\"margin-bottom:12px;\">\n          <div><strong>{{ item.description }}</strong> \u00b7 {{ item.total_qty }}</div>\n          <div class=\"bar\"><span style=\"width: {{ (item.total_qty / max_qty * 100) if max_qty else 0 }}%\"></span></div>\n        </div>\n      {% endfor %}\n    {% else %}\n      <div class=\"notice\">No usage yet.</div>\n    {% endif %}\n  </div>\n\n  <div class=\"card\">\n    <h2>Most Trips per Employee</h2>\n    {% if stats.trips %}\n      {% set max_trip = stats.trips[0].trips or 1 %}\n      {% for t in stats.trips %}\n        <div style=\"margin-bottom:12px;\">\n          <div><strong>{{ t.employee }}</strong> \u00b7 {{ t.trips }} trips</div>\n          <div class=\"bar\"><span style=\"width: {{ (t.trips / max_trip * 100) if max_trip else 0 }}%\"></span></div>\n        </div>\n      {% endfor %}\n    {% else %}\n      <div class=\"notice\">No trip data yet.</div>\n    {% endif %}\n  </div>\n</div>\n\n<div class=\"card\">\n  <h2>Recent Requisitions</h2>\n  <div class=\"table-wrap\">\n    <table>\n      <thead><tr><th>Req #</th><th>Requester</th><th>Department</th><th>Status</th><th>Updated</th></tr></thead>\n      <tbody>\n      {% for req in requisitions %}\n        <tr>\n          <td><a href=\"/requisitions/{{ req.id }}\">{{ req.req_no }}</a></td>\n          <td>{{ req.requester }}</td>\n          <td>{{ req.department }}</td>\n          <td><span class=\"status {{ req.status|lower|replace(' ','-') }}\">{{ req.status }}</span></td>\n          <td>{{ req.updated_at }}</td>\n        </tr>\n      {% endfor %}\n      </tbody>\n    </table>\n  </div>\n</div>\n{% endblock %}\n"
INVENTORY_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <h2>Inventory Tracking</h2>\n  <p class=\"small\">Add items, update stock, and issue inventory to employees or departments.</p>\n\n  <h3>Add / Update Item</h3>\n  <form method=\"post\" action=\"/inventory/add\">\n    <div class=\"form-row three\">\n      <div><label>Part #</label><input name=\"part_no\" required></div>\n      <div><label>Description</label><input name=\"description\" required></div>\n      <div><label>Vendor</label><input name=\"vendor\"></div>\n    </div>\n    <div class=\"form-row four\">\n      <div><label>On Hand</label><input name=\"on_hand\" type=\"number\" value=\"0\" min=\"0\"></div>\n      <div><label>Min Level</label><input name=\"min_level\" type=\"number\" value=\"0\" min=\"0\"></div>\n      <div><label>Reorder Qty</label><input name=\"reorder_qty\" type=\"number\" value=\"0\" min=\"0\"></div>\n      <div><label>Unit Cost</label><input name=\"unit_cost\" type=\"number\" step=\"0.01\" value=\"0\"></div>\n    </div>\n    <div class=\"form-actions\">\n      <input type=\"submit\" class=\"btn primary\" value=\"Save Item\">\n    </div>\n  </form>\n</div>\n\n<div class=\"grid cols-2\">\n  <div class=\"card\">\n    <h3>Issue Inventory</h3>\n    <form method=\"post\" action=\"/inventory/issue\">\n      <div class=\"form-row two\">\n        <div>\n          <label>Employee / Issued To</label>\n          <select name=\"employee\" required>\n            {% for u in users %}\n              <option value=\"{{ u.full_name }}\">{{ u.full_name }} ({{ u.role }})</option>\n            {% endfor %}\n          </select>\n        </div>\n        <div>\n          <label>Part #</label>\n          <input name=\"part_no\" id=\"issue_part_no\" list=\"partlist\" required>\n          <datalist id=\"partlist\">\n            {% for item in items %}\n              <option value=\"{{ item.part_no }}\">{{ item.description }}</option>\n            {% endfor %}\n          </datalist>\n        </div>\n      </div>\n      <div class=\"form-row two\">\n        <div><label>Quantity</label><input name=\"qty\" type=\"number\" min=\"1\" value=\"1\"></div>\n        <div style=\"display:flex; align-items:end;\"><input type=\"submit\" class=\"btn success\" value=\"Issue\"></div>\n      </div>\n    </form>\n  </div>\n\n  <div class=\"card\">\n    <h3>Inventory Snapshot</h3>\n    <div class=\"table-wrap\">\n      <table>\n        <thead><tr><th>Part #</th><th>Description</th><th>On Hand</th><th>Min</th><th>Reorder</th><th>Cost</th></tr></thead>\n        <tbody>\n        {% for item in items %}\n          <tr>\n            <td>{{ item.part_no }}</td>\n            <td>{{ item.description }}</td>\n            <td>{{ item.on_hand }}</td>\n            <td>{{ item.min_level }}</td>\n            <td>{{ item.reorder_qty }}</td>\n            <td>{{ money(item.unit_cost) }}</td>\n          </tr>\n        {% endfor %}\n        </tbody>\n      </table>\n    </div>\n  </div>\n</div>\n{% endblock %}\n"
REQUISITIONS_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <div style=\"display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; align-items:center;\">\n    <div>\n      <h2>Requisitions</h2>\n      <div class=\"small\">Workflow: Draft \u2192 Awaiting First Approver \u2192 Buyer Verification \u2192 Final Approval \u2192 PO Attachment \u2192 Ordered \u2192 Received</div>\n    </div>\n    <a class=\"btn primary\" href=\"/requisitions/new\">New Requisition</a>\n  </div>\n\n  <form method=\"get\" style=\"margin:16px 0;\">\n    <div class=\"form-row two\">\n      <div>\n        <label>Filter by Status</label>\n        <select name=\"status\" onchange=\"this.form.submit()\">\n          <option value=\"\">All</option>\n          {% for s in status_flow %}\n            <option value=\"{{ s }}\" {% if selected_status == s %}selected{% endif %}>{{ s }}</option>\n          {% endfor %}\n        </select>\n      </div>\n      <div style=\"display:flex; align-items:end;\">\n        <input type=\"submit\" class=\"btn\" value=\"Filter\">\n      </div>\n    </div>\n  </form>\n\n  <div class=\"table-wrap\">\n    <table>\n      <thead><tr><th>Req #</th><th>Requester</th><th>Department</th><th>Status</th><th>Updated</th><th>Total</th></tr></thead>\n      <tbody>\n      {% for req in requisitions %}\n        <tr>\n          <td><a href=\"/requisitions/{{ req.id }}\">{{ req.req_no }}</a></td>\n          <td>{{ req.requester }}</td>\n          <td>{{ req.department }}</td>\n          <td><span class=\"status {{ req.status|lower|replace(' ','-') }}\">{{ req.status }}</span></td>\n          <td>{{ req.updated_at }}</td>\n          <td>{{ money(requisition_total(req.id)) }}</td>\n        </tr>\n      {% endfor %}\n      </tbody>\n    </table>\n  </div>\n</div>\n{% endblock %}\n"
REQUISITION_NEW_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <h2>New Requisition</h2>\n  <p class=\"small\">Add as many items as needed, then submit into the approval workflow.</p>\n\n  <form method=\"post\" action=\"/requisitions/new\" id=\"reqForm\">\n    <div class=\"form-row two\">\n      <div><label>Requester</label><input name=\"requester\" required value=\"{{ user.full_name }}\"></div>\n      <div><label>Department</label><input name=\"department\" required value=\"{{ user.role.replace('_',' ').title() }}\"></div>\n    </div>\n    <div><label>Notes</label><textarea name=\"notes\" placeholder=\"Optional notes for approvers\"></textarea></div>\n\n    <div class=\"card\" style=\"margin-top:16px; background: rgba(255,255,255,0.02);\">\n      <div style=\"display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;\">\n        <h3 style=\"margin:0;\">Line Items</h3>\n        <button type=\"button\" class=\"btn info\" id=\"addLineBtn\">Add Line</button>\n      </div>\n\n      <div class=\"table-wrap\" style=\"margin-top:12px;\">\n        <table id=\"lineTable\">\n          <thead>\n            <tr><th>Part #</th><th>Description</th><th>Qty</th><th>Unit Cost</th><th></th></tr>\n          </thead>\n          <tbody>\n            <tr class=\"line-row\">\n              <td>\n                <input name=\"part_no\" list=\"partlist\" class=\"part-input\" placeholder=\"Part #\">\n              </td>\n              <td><input name=\"description\" class=\"desc-input\" placeholder=\"Description\"></td>\n              <td><input name=\"qty\" type=\"number\" min=\"1\" value=\"1\"></td>\n              <td><input name=\"unit_cost\" type=\"number\" step=\"0.01\" value=\"0\"></td>\n              <td><button type=\"button\" class=\"btn danger remove-line\">X</button></td>\n            </tr>\n          </tbody>\n        </table>\n        <datalist id=\"partlist\">\n          {% for item in items %}\n          <option value=\"{{ item.part_no }}\">{{ item.description }}</option>\n          {% endfor %}\n        </datalist>\n      </div>\n    </div>\n\n    <div class=\"form-actions\">\n      <input type=\"submit\" class=\"btn primary\" value=\"Create Requisition\">\n    </div>\n  </form>\n</div>\n{% endblock %}\n"
REQUISITION_DETAIL_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <div style=\"display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;\">\n    <div>\n      <h2>{{ req.req_no }}</h2>\n      <div class=\"small\">{{ req.requester }} \u00b7 {{ req.department }} \u00b7 Created {{ req.created_at }}</div>\n      <div style=\"margin-top:8px;\"><span class=\"status {{ req.status|lower|replace(' ','-') }}\">{{ req.status }}</span></div>\n    </div>\n    <div class=\"notice\">\n      <strong>Current Step</strong>\n      <div class=\"small\">\n        {% if req.status == \"Draft\" %}Awaiting submission from requester.\n        {% elif req.status == \"Awaiting First Approver\" %}Waiting on first approver.\n        {% elif req.status == \"Awaiting Buyer Price Verification\" %}Waiting on buyer price verification.\n        {% elif req.status == \"Awaiting Plant Manager Final Approval\" %}Waiting on plant manager final approval.\n        {% elif req.status == \"Awaiting Buyer PO Attachment\" %}Buyer may attach purchase order.\n        {% elif req.status == \"Ordered\" %}PO attached, ready to receive.\n        {% elif req.status == \"Partially Received\" %}Some items have been received.\n        {% elif req.status == \"Received\" %}Fully received.\n        {% else %}{{ req.status }}{% endif %}\n      </div>\n    </div>\n  </div>\n  {% if req.notes %}\n    <div class=\"notice\" style=\"margin-top:12px;\"><strong>Notes:</strong> {{ req.notes }}</div>\n  {% endif %}\n</div>\n\n<div class=\"grid cols-2\">\n  <div class=\"card\">\n    <h3>Line Items</h3>\n    <div class=\"table-wrap\">\n      <table>\n        <thead><tr><th>Part #</th><th>Description</th><th>Qty</th><th>Unit Cost</th><th>Total</th><th>Received</th></tr></thead>\n        <tbody>\n          {% for line in lines %}\n          <tr>\n            <td>{{ line.part_no }}</td>\n            <td>{{ line.description }}</td>\n            <td>{{ line.qty }}</td>\n            <td>{{ money(line.unit_cost) }}</td>\n            <td>{{ money(line.total_cost) }}</td>\n            <td>{{ line.received_qty }}</td>\n          </tr>\n          {% endfor %}\n        </tbody>\n      </table>\n    </div>\n\n    <h3 style=\"margin-top:18px;\">Actions</h3>\n    <div class=\"form-actions\">\n      {% if req.status == \"Draft\" %}\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"submit\">\n        <input type=\"hidden\" name=\"comment\" value=\"Submitted by requester\">\n        <button class=\"btn primary\" type=\"submit\">Submit to First Approver</button>\n      </form>\n      {% endif %}\n\n      {% if req.status == \"Awaiting First Approver\" and (user.role in ['first_approver','admin']) %}\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"approve_first\">\n        <input type=\"hidden\" name=\"comment\" value=\"\">\n        <button class=\"btn success\" type=\"submit\">Approve First Step</button>\n      </form>\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"reject\">\n        <input name=\"comment\" placeholder=\"Rejection reason\">\n        <button class=\"btn danger\" type=\"submit\">Reject</button>\n      </form>\n      {% endif %}\n\n      {% if req.status == \"Awaiting Buyer Price Verification\" and (user.role in ['buyer','admin']) %}\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"approve_buyer\">\n        <input type=\"hidden\" name=\"comment\" value=\"\">\n        <button class=\"btn success\" type=\"submit\">Approve Price Verification</button>\n      </form>\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"reject\">\n        <input name=\"comment\" placeholder=\"Rejection reason\">\n        <button class=\"btn danger\" type=\"submit\">Reject</button>\n      </form>\n      {% endif %}\n\n      {% if req.status == \"Awaiting Plant Manager Final Approval\" and (user.role in ['plant_manager','admin']) %}\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"approve_final\">\n        <input type=\"hidden\" name=\"comment\" value=\"\">\n        <button class=\"btn success\" type=\"submit\">Final Approve</button>\n      </form>\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/action\">\n        <input type=\"hidden\" name=\"action\" value=\"reject\">\n        <input name=\"comment\" placeholder=\"Rejection reason\">\n        <button class=\"btn danger\" type=\"submit\">Reject</button>\n      </form>\n      {% endif %}\n    </div>\n  </div>\n\n  <div class=\"card\">\n    <h3>Purchase Order</h3>\n    {% if po %}\n      <div class=\"notice\">\n        <div><strong>PO #:</strong> {{ po.po_number }}</div>\n        <div><strong>Vendor:</strong> {{ po.vendor }}</div>\n        <div><strong>Attached:</strong> {% if po.attachment %}<a href=\"/{{ po.attachment }}\">{{ po.attachment.split('/')[-1] }}</a>{% else %}No file{% endif %}</div>\n      </div>\n    {% endif %}\n    {% if req.status == \"Awaiting Buyer PO Attachment\" and (user.role in ['buyer','admin']) %}\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/attach-po\" enctype=\"multipart/form-data\">\n        <div class=\"form-row two\">\n          <div><label>PO Number</label><input name=\"po_number\" required placeholder=\"PO-12345\"></div>\n          <div><label>Vendor</label><input name=\"vendor\" placeholder=\"Vendor name\"></div>\n        </div>\n        <div class=\"file-drop dropzone\">\n          <label>Purchase Order PDF</label>\n          <input type=\"file\" name=\"po_file\" accept=\"application/pdf\" class=\"file-input\">\n          <div class=\"small\">Drag and drop the PO PDF here or tap to choose.</div>\n        </div>\n        <div class=\"form-actions\">\n          <button class=\"btn primary\" type=\"submit\">Attach PO</button>\n        </div>\n      </form>\n    {% endif %}\n\n    <h3 style=\"margin-top:18px;\">Receiving</h3>\n    {% if req.status in [\"Ordered\", \"Partially Received\"] and (user.role in ['receiver','buyer','plant_manager','admin']) %}\n      <form method=\"post\" action=\"/requisitions/{{ req.id }}/receive\" enctype=\"multipart/form-data\">\n        {% for line in lines %}\n          <div class=\"form-row three\">\n            <div><label>{{ line.part_no }} - Qty Ordered</label><input value=\"{{ line.qty }}\" disabled></div>\n            <div><label>Qty to Receive</label><input type=\"number\" name=\"received_qty_{{ line.id }}\" min=\"0\" max=\"{{ line.qty - line.received_qty }}\" value=\"{{ line.qty - line.received_qty }}\"></div>\n            <div><label>Remaining</label><input value=\"{{ line.qty - line.received_qty }}\" disabled></div>\n          </div>\n        {% endfor %}\n        <div class=\"file-drop dropzone\">\n          <label>Packing List PDF</label>\n          <input type=\"file\" name=\"packing_file\" accept=\"application/pdf\" class=\"file-input\">\n          <div class=\"small\">Drag and drop the packing list PDF here or tap to choose.</div>\n        </div>\n        <div style=\"margin-top:12px;\">\n          <label>Receiving Notes</label>\n          <textarea name=\"notes\" placeholder=\"Optional notes\"></textarea>\n        </div>\n        <div class=\"form-actions\">\n          <button class=\"btn success\" type=\"submit\">Mark Received</button>\n        </div>\n      </form>\n    {% endif %}\n\n    {% if receipt %}\n      <div class=\"notice\" style=\"margin-top:12px;\">\n        <strong>Latest Receipt</strong>\n        <div class=\"small\">Received by {{ receipt.received_by }} at {{ receipt.received_at }}</div>\n        {% if receipt.packing_list_file %}\n          <div><a href=\"/{{ receipt.packing_list_file }}\">Packing List File</a></div>\n        {% endif %}\n      </div>\n    {% endif %}\n  </div>\n</div>\n\n<div class=\"grid cols-2\">\n  <div class=\"card\">\n    <h3>Approval History</h3>\n    <div class=\"timeline\">\n      {% for h in history %}\n        <div class=\"timeline-item\">\n          <strong>{{ h.step_name }}</strong> \u00b7 {{ h.action }}\n          <div class=\"small\">{{ h.actor }} \u00b7 {{ h.created_at }}</div>\n          {% if h.comment %}<div class=\"small\">{{ h.comment }}</div>{% endif %}\n        </div>\n      {% endfor %}\n    </div>\n  </div>\n\n  <div class=\"card\">\n    <h3>Purchase Order / Receipt Status</h3>\n    <div class=\"notice\">\n      <div><strong>PO Number:</strong> {{ req.po_number or \"Not assigned yet\" }}</div>\n      <div><strong>Received By:</strong> {{ req.received_by or \"Not received yet\" }}</div>\n      <div><strong>Received At:</strong> {{ req.received_at or \"Not received yet\" }}</div>\n    </div>\n  </div>\n</div>\n{% endblock %}\n"
USERS_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <h2>User Administration</h2>\n  <form method=\"post\" action=\"/users/add\">\n    <div class=\"form-row three\">\n      <div><label>Username</label><input name=\"username\" required></div>\n      <div><label>Password</label><input name=\"password\" type=\"password\" required></div>\n      <div><label>Full Name</label><input name=\"full_name\" required></div>\n    </div>\n    <div class=\"form-row two\">\n      <div>\n        <label>Role</label>\n        <select name=\"role\" required>\n          {% for role in roles %}\n            <option value=\"{{ role }}\">{{ role.replace('_',' ').title() }}</option>\n          {% endfor %}\n        </select>\n      </div>\n      <div style=\"display:flex; align-items:end;\">\n        <input type=\"submit\" class=\"btn primary\" value=\"Add User\">\n      </div>\n    </div>\n  </form>\n</div>\n\n<div class=\"card\">\n  <h3>Current Users</h3>\n  <div class=\"table-wrap\">\n    <table>\n      <thead><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Status</th><th>Action</th></tr></thead>\n      <tbody>\n      {% for u in users %}\n        <tr>\n          <td>{{ u.username }}</td>\n          <td>{{ u.full_name }}</td>\n          <td>{{ u.role }}</td>\n          <td>{{ \"Active\" if u.active else \"Inactive\" }}</td>\n          <td>\n            <form method=\"post\" action=\"/users/{{ u.id }}/toggle\">\n              <button class=\"btn\" type=\"submit\">{% if u.active %}Deactivate{% else %}Activate{% endif %}</button>\n            </form>\n          </td>\n        </tr>\n      {% endfor %}\n      </tbody>\n    </table>\n  </div>\n</div>\n{% endblock %}\n"
REPORTS_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"grid cols-2\">\n  <div class=\"card\">\n    <h2>Top Items Used</h2>\n    {% if top_items %}\n      {% set max_qty = top_items[0].total_qty or 1 %}\n      {% for item in top_items %}\n        <div style=\"margin-bottom:12px;\">\n          <div><strong>{{ item.description }}</strong> \u00b7 {{ item.total_qty }} issued \u00b7 {{ money(item.total_cost) }}</div>\n          <div class=\"bar\"><span style=\"width: {{ (item.total_qty / max_qty * 100) if max_qty else 0 }}%\"></span></div>\n        </div>\n      {% endfor %}\n    {% else %}\n      <div class=\"notice\">No item usage has been logged yet.</div>\n    {% endif %}\n  </div>\n\n  <div class=\"card\">\n    <h2>Most Trips per Employee</h2>\n    {% if trips %}\n      {% set max_trip = trips[0].trips or 1 %}\n      {% for t in trips %}\n        <div style=\"margin-bottom:12px;\">\n          <div><strong>{{ t.employee }}</strong> \u00b7 {{ t.trips }} trips</div>\n          <div class=\"bar\"><span style=\"width: {{ (t.trips / max_trip * 100) if max_trip else 0 }}%\"></span></div>\n        </div>\n      {% endfor %}\n    {% else %}\n      <div class=\"notice\">No trip data yet.</div>\n    {% endif %}\n  </div>\n</div>\n\n<div class=\"card\">\n  <h2>Low Inventory Items</h2>\n  {% if low_stock %}\n    <div class=\"table-wrap\">\n      <table>\n        <thead><tr><th>Part #</th><th>Description</th><th>On Hand</th><th>Min Level</th><th>Reorder Qty</th></tr></thead>\n        <tbody>\n        {% for item in low_stock %}\n          <tr>\n            <td>{{ item.part_no }}</td>\n            <td>{{ item.description }}</td>\n            <td>{{ item.on_hand }}</td>\n            <td>{{ item.min_level }}</td>\n            <td>{{ item.reorder_qty }}</td>\n          </tr>\n        {% endfor %}\n        </tbody>\n      </table>\n    </div>\n  {% else %}\n    <div class=\"notice\">No low inventory items at this time.</div>\n  {% endif %}\n</div>\n{% endblock %}\n"
PURCHASE_ORDERS_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <h2>Purchase Orders</h2>\n  <div class=\"table-wrap\">\n    <table>\n      <thead><tr><th>PO #</th><th>Req #</th><th>Requester</th><th>Vendor</th><th>Status</th><th>Attachment</th><th>Created</th></tr></thead>\n      <tbody>\n      {% for po in pos %}\n        <tr>\n          <td>{{ po.po_number }}</td>\n          <td><a href=\"/requisitions/{{ po.requisition_id }}\">{{ po.req_no }}</a></td>\n          <td>{{ po.requester }}</td>\n          <td>{{ po.vendor }}</td>\n          <td><span class=\"status {{ po.status|lower|replace(' ','-') }}\">{{ po.status }}</span></td>\n          <td>{% if po.attachment %}<a href=\"/{{ po.attachment }}\">Open</a>{% else %}\u2014{% endif %}</td>\n          <td>{{ po.created_at }}</td>\n        </tr>\n      {% endfor %}\n      </tbody>\n    </table>\n  </div>\n</div>\n{% endblock %}\n"
RECEIVING_TEMPLATE = "\n{% extends \"base.html\" %}\n{% block content %}\n<div class=\"card\">\n  <h2>Receiving Queue</h2>\n  <div class=\"table-wrap\">\n    <table>\n      <thead><tr><th>Req #</th><th>Requester</th><th>Department</th><th>Status</th><th>PO #</th><th>Open</th></tr></thead>\n      <tbody>\n      {% for row in rows %}\n        <tr>\n          <td>{{ row.req_no }}</td>\n          <td>{{ row.requester }}</td>\n          <td>{{ row.department }}</td>\n          <td><span class=\"status {{ row.status|lower|replace(' ','-') }}\">{{ row.status }}</span></td>\n          <td>{{ row.po_number or \"\u2014\" }}</td>\n          <td><a class=\"btn\" href=\"/requisitions/{{ row.id }}\">Open</a></td>\n        </tr>\n      {% endfor %}\n      </tbody>\n    </table>\n  </div>\n</div>\n{% endblock %}\n"
STYLE_CSS = "\n:root {\n  --bg: #111;\n  --card: #1f1f1f;\n  --card-2: #262626;\n  --text: #f3f3f3;\n  --muted: #bcbcbc;\n  --accent: #f26522;\n  --accent-2: #ff8a4c;\n  --success: #2ecc71;\n  --warning: #f1c40f;\n  --danger: #e74c3c;\n  --info: #3498db;\n  --border: rgba(255,255,255,0.08);\n  --shadow: 0 10px 30px rgba(0,0,0,0.25);\n  --radius: 18px;\n  --nav-height: 70px;\n}\n\nbody.theme-dark-modern { --bg:#111111; --card:#1e1e1e; --card-2:#2a2a2a; --text:#f5f5f5; --muted:#cfcfcf; --accent:#f26522; --accent-2:#ff9b67; --border:rgba(255,255,255,0.08); }\nbody.theme-light-modern { --bg:#f4f4f4; --card:#ffffff; --card-2:#ffffff; --text:#111111; --muted:#444444; --accent:#f26522; --accent-2:#ff9b67; --border:rgba(0,0,0,0.08); }\nbody.theme-florida-state { --bg:#782F40; --card:#CEB888; --card-2:#e5d7b6; --text:#ffffff; --muted:#f5f5f5; --accent:#CEB888; --accent-2:#f0e0bc; --border:rgba(255,255,255,0.12); }\nbody.theme-ohio-state { --bg:#BB0000; --card:#666666; --card-2:#7a7a7a; --text:#ffffff; --muted:#f1f1f1; --accent:#ffffff; --accent-2:#ffefef; --border:rgba(255,255,255,0.12); }\nbody.theme-patriots { --bg:#0A2342; --card:#C60C30; --card-2:#d43a56; --text:#ffffff; --muted:#f3f3f3; --accent:#ffffff; --accent-2:#d6e4ff; --border:rgba(255,255,255,0.12); }\nbody.theme-cowboys { --bg:#041E42; --card:#869397; --card-2:#9aa6aa; --text:#ffffff; --muted:#f5f5f5; --accent:#ffffff; --accent-2:#eff6ff; --border:rgba(255,255,255,0.12); }\nbody.theme-cardinals { --bg:#97233F; --card:#000000; --card-2:#111111; --text:#ffffff; --muted:#f2f2f2; --accent:#FFB612; --accent-2:#ffd66e; --border:rgba(255,255,255,0.12); }\n\n* { box-sizing: border-box; }\nhtml, body { margin: 0; padding: 0; min-height: 100%; background: var(--bg); color: var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, \"Segoe UI\", Arial, sans-serif; }\nbody { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }\na { color: var(--accent); text-decoration: none; }\na:hover { text-decoration: underline; }\nbutton, input, select, textarea { font: inherit; }\n.container { max-width: 1500px; margin: 0 auto; padding: 16px; padding-bottom: calc(16px + env(safe-area-inset-bottom)); }\n.topbar {\n  display:flex; align-items:center; justify-content:space-between; gap:12px;\n  padding:12px 16px; background: var(--card); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 50;\n  padding-top: calc(12px + env(safe-area-inset-top));\n}\n.brand { display:flex; align-items:center; gap:12px; font-weight:800; letter-spacing:0.3px; }\n.brand img { width:52px; height:52px; object-fit:contain; border-radius:12px; background: rgba(255,255,255,0.05); padding:4px; }\n.navlinks { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }\n.navlinks a, .navlinks button, .btn, .chip, .pill, input[type=\"submit\"] {\n  display:inline-flex; align-items:center; justify-content:center; min-height: 44px;\n  border:1px solid var(--border); background: var(--card-2); color: var(--text);\n  padding:10px 14px; border-radius:14px; cursor:pointer; font-weight:700;\n  box-shadow:none; transition: all .15s ease;\n}\n.navlinks a:hover, .btn:hover, .chip:hover, input[type=\"submit\"]:hover { transform: translateY(-1px); border-color: var(--accent); }\n.nav-right { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }\nselect, input, textarea {\n  width:100%; padding:12px 12px; min-height: 46px; border-radius:14px; border:1px solid var(--border);\n  background: var(--card-2); color: var(--text); outline:none;\n}\ninput, textarea { box-shadow: inset 0 0 0 1px transparent; }\ntextarea { min-height: 100px; resize: vertical; }\nlabel { display:block; font-size: 0.92rem; margin-bottom:6px; color: var(--muted); }\n.page-grid { display:grid; grid-template-columns: 280px 1fr; gap:16px; margin-top: 16px; align-items:start; }\n.page-grid.no-sidebar { grid-template-columns: 1fr; }\n.sidebar, .card {\n  background: var(--card); border:1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow);\n}\n.sidebar { padding:16px; height: fit-content; position: sticky; top: 92px; }\n.sidebar h3 { margin-top:0; margin-bottom:12px; }\n.sidebar a { display:block; padding:12px 12px; border-radius:14px; background: transparent; border:1px solid transparent; margin-bottom:8px; }\n.sidebar a:hover { background: var(--card-2); border-color: var(--border); }\n.content { min-width: 0; }\n.card { padding:16px; margin-bottom:16px; }\n.card h2, .card h3 { margin-top:0; }\n.grid { display:grid; gap:14px; }\n.grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }\n.grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }\n.grid.cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }\n.stat {\n  padding:18px; border-radius:18px; background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent);\n  border:1px solid var(--border);\n}\n.stat .label { color: var(--muted); font-size: 0.92rem; }\n.stat .value { font-size: clamp(1.4rem, 5vw, 2.25rem); font-weight: 900; margin-top:8px; }\n.flash { padding: 12px 14px; border-radius: 14px; margin-bottom: 16px; font-weight: 700; }\n.flash.success { background: rgba(46,204,113,0.14); border: 1px solid rgba(46,204,113,0.35); }\n.flash.error { background: rgba(231,76,60,0.14); border: 1px solid rgba(231,76,60,0.35); }\n.flash.info { background: rgba(52,152,219,0.14); border: 1px solid rgba(52,152,219,0.35); }\n.table-wrap { overflow-x:auto; -webkit-overflow-scrolling: touch; }\ntable { width:100%; border-collapse: collapse; }\nth, td { padding: 11px 10px; border-bottom: 1px solid var(--border); text-align:left; vertical-align: top; }\nth { color: var(--muted); font-size: 0.88rem; text-transform: uppercase; letter-spacing: 0.05em; }\ntr:hover td { background: rgba(255,255,255,0.02); }\n.status {\n  display:inline-flex; align-items:center; padding:7px 10px; border-radius: 999px; font-size:0.82rem; font-weight:800;\n  border:1px solid var(--border); white-space: nowrap;\n}\n.status.draft { background: rgba(255,255,255,0.06); }\n.status.awaiting-first-approver { background: rgba(52,152,219,0.16); }\n.status.awaiting-buyer-price-verification { background: rgba(241,196,15,0.16); }\n.status.awaiting-plant-manager-final-approval { background: rgba(155,89,182,0.16); }\n.status.awaiting-buyer-po-attachment { background: rgba(243,156,18,0.16); }\n.status.ordered { background: rgba(46,204,113,0.16); }\n.status.partially-received { background: rgba(241,196,15,0.2); }\n.status.received { background: rgba(46,204,113,0.2); }\n.status.rejected { background: rgba(231,76,60,0.2); }\n.bar { height: 12px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; margin: 6px 0 0; }\n.bar > span { display:block; height:100%; background: var(--accent); border-radius: 999px; }\n.small { color: var(--muted); font-size: 0.9rem; }\n.form-row { display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:12px; margin-bottom:12px; }\n.form-row.two { grid-template-columns: repeat(2, minmax(0,1fr)); }\n.form-row.three { grid-template-columns: repeat(3, minmax(0,1fr)); }\n.form-actions { display:flex; gap:10px; flex-wrap:wrap; margin-top: 12px; }\n.btn.primary, input[type=\"submit\"].primary { background: var(--accent); color:#fff; border-color: transparent; }\n.btn.danger { background: var(--danger); color:#fff; border-color: transparent; }\n.btn.success { background: var(--success); color:#fff; border-color: transparent; }\n.btn.info { background: var(--info); color:#fff; border-color: transparent; }\n.file-drop {\n  border: 2px dashed var(--border); border-radius: 16px; padding: 14px; background: rgba(255,255,255,0.03);\n}\n.file-drop.dragover { border-color: var(--accent); background: rgba(242,101,34,0.10); }\n.timeline { display:flex; flex-direction:column; gap:10px; }\n.timeline-item {\n  padding: 12px 14px; border-left: 4px solid var(--accent); background: rgba(255,255,255,0.03); border-radius: 12px;\n}\n.notice { padding: 12px 14px; border-radius: 14px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); margin-bottom: 14px; }\n.footer { margin-top: 24px; color: var(--muted); text-align:center; padding: 14px 0 28px; }\n.hidden { display:none; }\n.logo-banner { width:56px; height:56px; object-fit:contain; }\n.mobile-nav {\n  display:none;\n}\n.desktop-nav { display:flex; }\n\n@media (max-width: 1000px) {\n  .page-grid, .grid.cols-4, .grid.cols-3, .grid.cols-2, .form-row, .form-row.two, .form-row.three { grid-template-columns: 1fr; }\n  .sidebar { position: static; }\n  .topbar { flex-direction: column; align-items:flex-start; }\n  .desktop-nav { display:none; }\n  .mobile-nav {\n    display:grid;\n    grid-template-columns: repeat(3, 1fr);\n    gap:8px;\n    position: fixed;\n    left: 0;\n    right: 0;\n    bottom: 0;\n    z-index: 45;\n    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));\n    background: var(--card);\n    border-top: 1px solid var(--border);\n    box-shadow: 0 -8px 24px rgba(0,0,0,0.24);\n  }\n  .mobile-nav a {\n    display:flex;\n    justify-content:center;\n    align-items:center;\n    min-height: 44px;\n    text-align:center;\n    padding: 10px 8px;\n    border-radius: 14px;\n    background: var(--card-2);\n    color: var(--text);\n    border: 1px solid var(--border);\n    font-size: 0.9rem;\n    font-weight: 800;\n  }\n  .mobile-nav a.active {\n    border-color: var(--accent);\n    color: var(--accent);\n  }\n  .container { padding-bottom: calc(100px + env(safe-area-inset-bottom)); }\n}\n\n@media (max-width: 640px) {\n  .brand img { width:46px; height:46px; }\n  .topbar { padding: 12px; }\n  .container { padding: 12px; padding-bottom: calc(100px + env(safe-area-inset-bottom)); }\n  .card { padding: 14px; }\n  .mobile-nav { grid-template-columns: repeat(2, 1fr); }\n}\n"
APP_JS = "\ndocument.addEventListener(\"DOMContentLoaded\", () => {\n  const currentPath = (document.body.dataset.path || window.location.pathname || \"/\").replace(/\\/$/, \"\") || \"/\";\n  document.querySelectorAll(\".mobile-nav a, .desktop-nav a\").forEach(a => {\n    const href = (a.getAttribute(\"href\") || \"\").replace(/\\/$/, \"\") || \"/\";\n    if (href === currentPath) a.classList.add(\"active\");\n  });\n\n  const addLineBtn = document.getElementById(\"addLineBtn\");\n  const lineTable = document.getElementById(\"lineTable\");\n  if (addLineBtn && lineTable) {\n    addLineBtn.addEventListener(\"click\", () => {\n      const tbody = lineTable.querySelector(\"tbody\");\n      const row = tbody.querySelector(\".line-row\");\n      const clone = row.cloneNode(true);\n      clone.querySelectorAll(\"input\").forEach(inp => {\n        if (inp.name === \"qty\") inp.value = \"1\";\n        else if (inp.name === \"unit_cost\") inp.value = \"0\";\n        else inp.value = \"\";\n      });\n      tbody.appendChild(clone);\n      bindLineRow(clone);\n    });\n    bindLineRow(document.querySelector(\".line-row\"));\n  }\n\n  function bindLineRow(row) {\n    if (!row) return;\n    const part = row.querySelector(\".part-input\");\n    const desc = row.querySelector(\".desc-input\");\n    const remove = row.querySelector(\".remove-line\");\n    if (remove) {\n      remove.addEventListener(\"click\", () => {\n        const tbody = row.parentElement;\n        if (tbody.querySelectorAll(\".line-row\").length > 1) row.remove();\n      });\n    }\n    if (part) {\n      part.addEventListener(\"change\", async () => {\n        if (!part.value) return;\n        try {\n          const res = await fetch(`/api/items/${encodeURIComponent(part.value)}`);\n          const data = await res.json();\n          if (data.found) {\n            if (desc && !desc.value) desc.value = data.description;\n            const costInput = row.querySelector('input[name=\"unit_cost\"]');\n            if (costInput && (!costInput.value || costInput.value === \"0\")) costInput.value = data.unit_cost;\n          }\n        } catch (e) {}\n      });\n    }\n  }\n\n  document.querySelectorAll(\".dropzone\").forEach(zone => {\n    const input = zone.querySelector(\".file-input\");\n    if (!input) return;\n\n    zone.addEventListener(\"dragover\", (e) => {\n      e.preventDefault();\n      zone.classList.add(\"dragover\");\n    });\n    zone.addEventListener(\"dragleave\", () => zone.classList.remove(\"dragover\"));\n    zone.addEventListener(\"drop\", (e) => {\n      e.preventDefault();\n      zone.classList.remove(\"dragover\");\n      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {\n        input.files = e.dataTransfer.files;\n      }\n    });\n    zone.addEventListener(\"click\", () => input.click());\n  });\n});\n"
MANIFEST_JSON = "{\n  \"name\": \"Warehouse Enterprise ERP\",\n  \"short_name\": \"Warehouse ERP\",\n  \"start_url\": \"/\",\n  \"scope\": \"/\",\n  \"display\": \"standalone\",\n  \"background_color\": \"#111111\",\n  \"theme_color\": \"#111111\",\n  \"icons\": [\n    {\n      \"src\": \"/assets/images/icon-192.png\",\n      \"sizes\": \"192x192\",\n      \"type\": \"image/png\"\n    },\n    {\n      \"src\": \"/assets/images/icon-512.png\",\n      \"sizes\": \"512x512\",\n      \"type\": \"image/png\"\n    }\n  ]\n}"
SW_JS = "\nconst CACHE_NAME = 'wh-enterprise-v2';\nconst ASSETS = [\n  '/',\n  '/login',\n  '/static/style.css',\n  '/static/app.js',\n  '/static/manifest.json',\n  '/assets/images/apple-touch-icon.png',\n  '/assets/images/icon-192.png',\n  '/assets/images/icon-512.png'\n];\n\nself.addEventListener('install', event => {\n  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));\n});\n\nself.addEventListener('activate', event => {\n  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))).then(() => self.clients.claim()));\n});\n\nself.addEventListener('fetch', event => {\n  if (event.request.method !== 'GET') return;\n  event.respondWith(\n    caches.match(event.request).then(resp => resp || fetch(event.request).then(network => {\n      const copy = network.clone();\n      caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)).catch(()=>{});\n      return network;\n    }).catch(() => caches.match('/')))\n  );\n});\n"
INVENTORY_CSV_TEMPLATE = "Part #,Description,On Hand,Min Level,Reorder Qty,Unit Cost,Vendor\n1001,Gloves,200,50,150,1.25,Example Vendor\n1002,Bolts,500,100,300,0.10,Example Vendor\n1003,Zip Ties,250,50,200,0.08,Example Vendor\n"
REQUIREMENTS_TXT = "fastapi\nuvicorn\njinja2\npython-multipart\nitsdangerous\n"
README_TXT = "Warehouse Enterprise ERP\n\nRun on Windows:\n1. Install Python 3.11+\n2. Open Command Prompt in this folder\n3. Run: pip install -r requirements.txt\n4. Run: python WH_ENTERPRISE_WEB.py\n\nTo access from iPhone:\n1. Run the app on your PC\n2. Find the PC IP address (for example 192.168.1.25)\n3. Open Safari on iPhone and go to:\n   http://192.168.1.25:8000\n\nDefault login:\nadmin / admin123\n\nOther sample users:\nrequester / requester123\napprover / approver123\nbuyer / buyer123\nplant / plant123\nreceiver / receiver123\n\nThe app uses SQLite, local uploads, and the local assets folder, so it is portable as a folder.\n"
RUN_BAT = "@echo off\ncd /d %~dp0\npython -m pip install -r requirements.txt\npython WH_ENTERPRISE_WEB.py\npause\n"


THEMES = {
    "Dark Modern": {"class": "theme-dark-modern", "logo": "arcosa.png"},
    "Light Modern": {"class": "theme-light-modern", "logo": "arcosa.png"},
    "Florida State": {"class": "theme-florida-state", "logo": "florida state.png"},
    "Ohio State": {"class": "theme-ohio-state", "logo": "ohio state.png"},
    "Patriots": {"class": "theme-patriots", "logo": "patriots.png"},
    "Cowboys": {"class": "theme-cowboys", "logo": "cowboys.png"},
    "Cardinals": {"class": "theme-cardinals", "logo": "cardinals.png"},
}

STATUS_FLOW = [
    "Draft",
    "Awaiting First Approver",
    "Awaiting Buyer Price Verification",
    "Awaiting Plant Manager Final Approval",
    "Awaiting Buyer PO Attachment",
    "Ordered",
    "Partially Received",
    "Received",
    "Rejected",
]

ROLES = [
    "admin",
    "requester",
    "first_approver",
    "buyer",
    "plant_manager",
    "receiver",
]

DEFAULT_USERS = [
    ("admin", "admin123", "Administrator", "admin"),
    ("requester", "requester123", "Requester User", "requester"),
    ("approver", "approver123", "Department Manager", "first_approver"),
    ("buyer", "buyer123", "Buyer User", "buyer"),
    ("plant", "plant123", "Plant Manager", "plant_manager"),
    ("receiver", "receiver123", "Receiving Clerk", "receiver"),
]

DEFAULT_THEMES = "Dark Modern"

SECRET_KEY_FILE = BASE_DIR / ".secret_key"
if SECRET_KEY_FILE.exists():
    SECRET_KEY = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(SECRET_KEY, encoding="utf-8")

SESSION_SERIALIZER = URLSafeSerializer(SECRET_KEY, salt="wh-enterprise-session")

app = FastAPI(title="Warehouse Enterprise ERP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["themes"] = list(THEMES.keys())
templates.env.globals["status_flow"] = STATUS_FLOW
templates.env.globals["now"] = datetime.utcnow


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
        ).hex()
        return hmac.compare_digest(computed, digest)
    except Exception:
        return False


def generate_reference(prefix: str, conn: sqlite3.Connection) -> str:
    date_prefix = datetime.now().strftime("%Y%m%d")
    cur = conn.execute(
        f"SELECT COUNT(*) AS c FROM {('requisitions' if prefix == 'RQ' else 'purchase_orders')} "
        "WHERE created_at LIKE ?",
        (f"{datetime.now().strftime('%Y-%m-%d')}%",),
    )
    count = cur.fetchone()["c"] + 1
    return f"{prefix}-{date_prefix}-{count:04d}"


def init_templates() -> None:
    (TEMPLATE_DIR / "base.html").write_text(BASE_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "login.html").write_text(LOGIN_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "dashboard.html").write_text(DASHBOARD_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "inventory.html").write_text(INVENTORY_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "requisitions.html").write_text(REQUISITIONS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "requisition_new.html").write_text(REQUISITION_NEW_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "requisition_detail.html").write_text(REQUISITION_DETAIL_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "users.html").write_text(USERS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "reports.html").write_text(REPORTS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "purchase_orders.html").write_text(PURCHASE_ORDERS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "receiving.html").write_text(RECEIVING_TEMPLATE, encoding="utf-8")


def init_static() -> None:
    (STATIC_DIR / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (STATIC_DIR / "app.js").write_text(APP_JS, encoding="utf-8")
    (STATIC_DIR / "manifest.json").write_text(MANIFEST_JSON, encoding="utf-8")
    (STATIC_DIR / "sw.js").write_text(SW_JS, encoding="utf-8")
    (BASE_DIR / "requirements.txt").write_text(REQUIREMENTS_TXT, encoding="utf-8")
    (BASE_DIR / "README.txt").write_text(README_TXT, encoding="utf-8")
    (BASE_DIR / "run.bat").write_text(RUN_BAT, encoding="utf-8")
    # inventory template
    if not (BASE_DIR / "inventory.csv").exists():
        (BASE_DIR / "inventory.csv").write_text(INVENTORY_CSV_TEMPLATE, encoding="utf-8")


def copy_assets() -> None:
    for name in ["arcosa.png", "florida state.png", "ohio state.png", "patriots.png", "cowboys.png", "cardinals.png"]:
        src = Path("/mnt/data") / name
        dst = ASSET_DIR / name
        if src.exists():
            dst.write_bytes(src.read_bytes())


@contextmanager
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def seed_inventory_from_csv(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT COUNT(*) AS c FROM inventory_items")
    if cur.fetchone()["c"] > 0:
        return
    csv_path = BASE_DIR / "inventory.csv"
    if not csv_path.exists():
        return
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            part_no = (row.get("Part #") or row.get("Part") or "").strip()
            if not part_no:
                continue
            desc = (row.get("Description") or "").strip()
            on_hand = int(float(row.get("On Hand") or 0))
            min_level = int(float(row.get("Min Level") or 0))
            reorder_qty = int(float(row.get("Reorder Qty") or 0))
            unit_cost = float(row.get("Unit Cost") or row.get("Cost") or 0)
            vendor = (row.get("Vendor") or "").strip()
            conn.execute(
                """
                INSERT INTO inventory_items (part_no, description, on_hand, min_level, reorder_qty, unit_cost, vendor, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (part_no, desc, on_hand, min_level, reorder_qty, unit_cost, vendor, now_iso()),
            )


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_no TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                on_hand INTEGER NOT NULL DEFAULT 0,
                min_level INTEGER NOT NULL DEFAULT 0,
                reorder_qty INTEGER NOT NULL DEFAULT 0,
                unit_cost REAL NOT NULL DEFAULT 0,
                vendor TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee TEXT NOT NULL,
                part_no TEXT NOT NULL,
                description TEXT NOT NULL,
                qty INTEGER NOT NULL,
                unit_cost REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                issued_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS requisitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT UNIQUE NOT NULL,
                requester TEXT NOT NULL,
                department TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT DEFAULT '',
                current_step INTEGER NOT NULL DEFAULT 0,
                po_number TEXT DEFAULT '',
                po_file TEXT DEFAULT '',
                packing_list_file TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                received_at TEXT DEFAULT '',
                received_by TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS requisition_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                part_no TEXT NOT NULL,
                description TEXT NOT NULL,
                qty INTEGER NOT NULL,
                unit_cost REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                received_qty INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS approval_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                comment TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                po_number TEXT UNIQUE NOT NULL,
                vendor TEXT DEFAULT '',
                attachment TEXT DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                received_by TEXT NOT NULL,
                packing_list_file TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                received_at TEXT NOT NULL,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );
            """
        )
        seed_inventory_from_csv(conn)
        cur = conn.execute("SELECT COUNT(*) AS c FROM users")
        if cur.fetchone()["c"] == 0:
            for username, pw, full_name, role in DEFAULT_USERS:
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (username, hash_password(pw), full_name, role, now_iso()),
                )


def get_theme_name(request: Request) -> str:
    theme = request.cookies.get("theme", DEFAULT_THEMES)
    return theme if theme in THEMES else DEFAULT_THEMES


def get_user_from_session(request: Request) -> Optional[dict[str, Any]]:
    raw = request.cookies.get("session")
    if not raw:
        return None
    try:
        data = SESSION_SERIALIZER.loads(raw)
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND active = 1",
                (data.get("username"),),
            ).fetchone()
            if row:
                return dict(row)
    except BadSignature:
        return None
    except Exception:
        return None
    return None


def auth_context(request: Request) -> dict[str, Any]:
    user = get_user_from_session(request)
    theme_name = get_theme_name(request)
    return {
        "user": user,
        "theme_name": theme_name,
        "theme_class": THEMES[theme_name]["class"],
        "logo_name": THEMES[theme_name]["logo"],
        "current_year": datetime.now().year,
    }


def require_login(request: Request) -> dict[str, Any]:
    user = get_user_from_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(user: dict[str, Any], roles: list[str]) -> None:
    if user["role"] not in roles and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")


def redirect_with_msg(path: str, msg: str = "", kind: str = "success") -> RedirectResponse:
    from urllib.parse import quote
    url = path
    if msg:
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}msg={quote(msg)}&kind={quote(kind)}"
    return RedirectResponse(url, status_code=303)


def money(value: float | int | None) -> str:
    try:
        return f"${float(value or 0):,.2f}"
    except Exception:
        return "$0.00"


templates.env.globals["money"] = money


def requisition_total(req_id: int) -> float:
    with db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(total_cost),0) AS t FROM requisition_lines WHERE requisition_id = ?", (req_id,)).fetchone()
        return float(row["t"] or 0)

def dashboard_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    low_stock = conn.execute(
        "SELECT * FROM inventory_items WHERE on_hand <= min_level ORDER BY (on_hand - min_level) ASC, description ASC"
    ).fetchall()

    pending = conn.execute(
        """
        SELECT * FROM requisitions
        WHERE status IN (
            'Awaiting First Approver',
            'Awaiting Buyer Price Verification',
            'Awaiting Plant Manager Final Approval',
            'Awaiting Buyer PO Attachment',
            'Ordered'
        )
        ORDER BY datetime(updated_at) DESC
        LIMIT 10
        """
    ).fetchall()

    open_req = conn.execute(
        "SELECT COUNT(*) AS c FROM requisitions WHERE status NOT IN ('Received','Rejected')"
    ).fetchone()["c"]

    received = conn.execute(
        "SELECT COUNT(*) AS c FROM requisitions WHERE status = 'Received'"
    ).fetchone()["c"]

    total_items = conn.execute("SELECT COUNT(*) AS c FROM inventory_items").fetchone()["c"]
    total_value = conn.execute("SELECT COALESCE(SUM(on_hand * unit_cost),0) AS v FROM inventory_items").fetchone()["v"]

    top_items = conn.execute(
        """
        SELECT description, SUM(qty) AS total_qty
        FROM usage_log
        GROUP BY description
        ORDER BY total_qty DESC, description ASC
        LIMIT 10
        """
    ).fetchall()

    trip_rows = conn.execute("SELECT employee, issued_at FROM usage_log ORDER BY employee, datetime(issued_at)").fetchall()
    trips = compute_trips(trip_rows)

    return {
        "low_stock": low_stock,
        "pending": pending,
        "open_req": open_req,
        "received": received,
        "total_items": total_items,
        "total_value": total_value,
        "top_items": top_items,
        "trips": trips,
    }


def compute_trips(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    by_emp: dict[str, list[datetime]] = defaultdict(list)
    for row in rows:
        by_emp[row["employee"]].append(datetime.fromisoformat(row["issued_at"]))
    result = []
    for emp, times in by_emp.items():
        times.sort()
        trip_count = 0
        last = None
        for t in times:
            if last is None or (t - last).total_seconds() > 60:
                trip_count += 1
            last = t
        result.append({"employee": emp, "trips": trip_count})
    result.sort(key=lambda x: x["trips"], reverse=True)
    return result


def current_step_name(status: str) -> str:
    return status


def next_status_for(action: str, current: str) -> str:
    mapping = {
        ("submit", "Draft"): "Awaiting First Approver",
        ("approve_first", "Awaiting First Approver"): "Awaiting Buyer Price Verification",
        ("approve_buyer", "Awaiting Buyer Price Verification"): "Awaiting Plant Manager Final Approval",
        ("approve_final", "Awaiting Plant Manager Final Approval"): "Awaiting Buyer PO Attachment",
        ("attach_po", "Awaiting Buyer PO Attachment"): "Ordered",
    }
    return mapping.get((action, current), current)


@app.on_event("startup")
def startup() -> None:
    templates.env.globals["requisition_total"] = requisition_total
    templates.env.globals["money"] = money
    init_templates()
    init_static()
    copy_assets()
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        stats = dashboard_stats(conn)
        requisitions = conn.execute(
            "SELECT * FROM requisitions ORDER BY datetime(updated_at) DESC LIMIT 10"
        ).fetchall()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            **auth_context(request),
            "stats": stats,
            "requisitions": requisitions,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_user_from_session(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            **auth_context(request),
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), theme: str = Form(DEFAULT_THEMES)):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username.strip(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return redirect_with_msg("/login", "Invalid username or password.", "error")
    token = SESSION_SERIALIZER.dumps({"username": row["username"]})
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("session", token, httponly=True, samesite="lax")
    if theme in THEMES:
        resp.set_cookie("theme", theme, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp


@app.post("/theme")
def set_theme(request: Request, theme: str = Form(DEFAULT_THEMES)):
    resp = RedirectResponse(request.headers.get("referer", "/"), status_code=303)
    resp.set_cookie("theme", theme if theme in THEMES else DEFAULT_THEMES, samesite="lax")
    return resp


@app.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        items = conn.execute("SELECT * FROM inventory_items ORDER BY on_hand ASC, description ASC").fetchall()
        users = conn.execute("SELECT full_name, role FROM users WHERE active = 1 ORDER BY full_name ASC").fetchall()
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            **auth_context(request),
            "items": items,
            "users": users,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/inventory/add")
def add_inventory_item(
    request: Request,
    part_no: str = Form(...),
    description: str = Form(...),
    on_hand: int = Form(0),
    min_level: int = Form(0),
    reorder_qty: int = Form(0),
    unit_cost: float = Form(0),
    vendor: str = Form(""),
):
    user = require_login(request)
    require_role(user, ["admin", "plant_manager", "buyer"])
    with db() as conn:
        conn.execute(
            """
            INSERT INTO inventory_items (part_no, description, on_hand, min_level, reorder_qty, unit_cost, vendor, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(part_no) DO UPDATE SET
                description=excluded.description,
                on_hand=excluded.on_hand,
                min_level=excluded.min_level,
                reorder_qty=excluded.reorder_qty,
                unit_cost=excluded.unit_cost,
                vendor=excluded.vendor,
                updated_at=excluded.updated_at
            """,
            (part_no.strip(), description.strip(), on_hand, min_level, reorder_qty, unit_cost, vendor.strip(), now_iso()),
        )
    return redirect_with_msg("/inventory", "Inventory item saved.")


@app.post("/inventory/{item_id}/update")
def update_inventory_item(
    request: Request,
    item_id: int,
    description: str = Form(...),
    on_hand: int = Form(0),
    min_level: int = Form(0),
    reorder_qty: int = Form(0),
    unit_cost: float = Form(0),
    vendor: str = Form(""),
):
    user = require_login(request)
    require_role(user, ["admin", "plant_manager", "buyer"])
    with db() as conn:
        conn.execute(
            """
            UPDATE inventory_items
            SET description=?, on_hand=?, min_level=?, reorder_qty=?, unit_cost=?, vendor=?, updated_at=?
            WHERE id=?
            """,
            (description.strip(), on_hand, min_level, reorder_qty, unit_cost, vendor.strip(), now_iso(), item_id),
        )
    return redirect_with_msg("/inventory", "Inventory item updated.")


@app.post("/inventory/issue")
def issue_inventory(
    request: Request,
    employee: str = Form(...),
    part_no: str = Form(...),
    qty: int = Form(...),
):
    user = require_login(request)
    require_role(user, ["admin", "requester", "buyer", "plant_manager", "receiver", "first_approver"])
    if qty <= 0:
        return redirect_with_msg("/inventory", "Quantity must be greater than zero.", "error")
    with db() as conn:
        item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (part_no.strip(),)).fetchone()
        if not item:
            return redirect_with_msg("/inventory", "Item not found.", "error")
        if item["on_hand"] < qty:
            return redirect_with_msg("/inventory", "Not enough on hand to issue.", "error")
        new_on_hand = item["on_hand"] - qty
        total_cost = qty * float(item["unit_cost"] or 0)
        conn.execute(
            "UPDATE inventory_items SET on_hand=?, updated_at=? WHERE id=?",
            (new_on_hand, now_iso(), item["id"]),
        )
        conn.execute(
            """
            INSERT INTO usage_log (employee, part_no, description, qty, unit_cost, total_cost, issued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (employee.strip(), item["part_no"], item["description"], qty, float(item["unit_cost"] or 0), total_cost, now_iso()),
        )
    return redirect_with_msg("/inventory", "Item issued and inventory updated.")


@app.get("/api/items/{part_no}")
def api_item(part_no: str):
    with db() as conn:
        item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (part_no.strip(),)).fetchone()
        if not item:
            return JSONResponse({"found": False})
        return JSONResponse(
            {
                "found": True,
                "part_no": item["part_no"],
                "description": item["description"],
                "unit_cost": item["unit_cost"],
                "on_hand": item["on_hand"],
                "min_level": item["min_level"],
                "reorder_qty": item["reorder_qty"],
                "vendor": item["vendor"],
            }
        )


@app.get("/requisitions", response_class=HTMLResponse)
def requisitions_page(request: Request, status: str = ""):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        if status:
            rows = conn.execute("SELECT * FROM requisitions WHERE status = ? ORDER BY datetime(created_at) DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM requisitions ORDER BY datetime(created_at) DESC").fetchall()
    return templates.TemplateResponse(
        "requisitions.html",
        {
            "request": request,
            **auth_context(request),
            "requisitions": rows,
            "selected_status": status,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/requisitions/new", response_class=HTMLResponse)
def requisition_new(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        items = conn.execute("SELECT * FROM inventory_items ORDER BY description ASC").fetchall()
    return templates.TemplateResponse(
        "requisition_new.html",
        {
            "request": request,
            **auth_context(request),
            "items": items,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/requisitions/new")
async def create_requisition(
    request: Request,
    requester: str = Form(...),
    department: str = Form(...),
    notes: str = Form(""),
    part_no: list[str] = Form(default=[]),
    description: list[str] = Form(default=[]),
    qty: list[int] = Form(default=[]),
    unit_cost: list[float] = Form(default=[]),
):
    user = require_login(request)
    require_role(user, ["admin", "requester", "buyer", "plant_manager", "first_approver"])
    lines = []
    with db() as conn:
        for i in range(max(len(part_no), len(description), len(qty), len(unit_cost))):
            pn = (part_no[i].strip() if i < len(part_no) else "")
            desc = (description[i].strip() if i < len(description) else "")
            q = int(qty[i]) if i < len(qty) and str(qty[i]).strip() else 0
            cost = float(unit_cost[i]) if i < len(unit_cost) and str(unit_cost[i]).strip() else 0.0
            if not pn and not desc and q <= 0:
                continue
            if pn and not desc:
                item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (pn,)).fetchone()
                if item:
                    desc = item["description"]
                    if cost <= 0:
                        cost = float(item["unit_cost"] or 0)
            if q <= 0:
                continue
            if not pn:
                pn = f"MANUAL-{len(lines)+1}"
            lines.append((pn, desc, q, cost))
        if not lines:
            return redirect_with_msg("/requisitions/new", "Add at least one line item.", "error")
        req_no = generate_reference("RQ", conn)
        conn.execute(
            """
            INSERT INTO requisitions (req_no, requester, department, status, notes, current_step, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (req_no, requester.strip(), department.strip(), "Draft", notes.strip(), now_iso(), now_iso()),
        )
        req_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        for pn, desc, q, cost in lines:
            conn.execute(
                """
                INSERT INTO requisition_lines (requisition_id, part_no, description, qty, unit_cost, total_cost, received_qty)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (req_id, pn, desc, q, cost, q * cost),
            )
        conn.execute(
            """
            INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
            VALUES (?, 'Draft', ?, 'Created', ?, ?)
            """,
            (req_id, user["full_name"], notes.strip(), now_iso()),
        )
    return redirect_with_msg(f"/requisitions/{req_id}", f"Requisition {req_no} created.")


@app.get("/requisitions/{req_id}", response_class=HTMLResponse)
def requisition_detail(request: Request, req_id: int):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        lines = conn.execute("SELECT * FROM requisition_lines WHERE requisition_id = ? ORDER BY id", (req_id,)).fetchall()
        history = conn.execute(
            "SELECT * FROM approval_history WHERE requisition_id = ? ORDER BY datetime(created_at) ASC, id ASC",
            (req_id,),
        ).fetchall()
        po = conn.execute("SELECT * FROM purchase_orders WHERE requisition_id = ?", (req_id,)).fetchone()
        receipt = conn.execute("SELECT * FROM receipts WHERE requisition_id = ? ORDER BY datetime(received_at) DESC LIMIT 1", (req_id,)).fetchone()
        items = conn.execute("SELECT * FROM inventory_items ORDER BY description ASC").fetchall()
    return templates.TemplateResponse(
        "requisition_detail.html",
        {
            "request": request,
            **auth_context(request),
            "req": req,
            "lines": lines,
            "history": history,
            "po": po,
            "receipt": receipt,
            "items": items,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/requisitions/{req_id}/action")
async def requisition_action(
    request: Request,
    req_id: int,
    action: str = Form(...),
    comment: str = Form(""),
    po_number: str = Form(""),
    vendor: str = Form(""),
    packing_list: UploadFile | None = File(default=None),
):
    user = require_login(request)
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        current_status = req["status"]

        def log(step: str, action_text: str, comment_text: str = "") -> None:
            conn.execute(
                """
                INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req_id, step, user["full_name"], action_text, comment_text, now_iso()),
            )

        if action == "submit":
            require_role(user, ["admin", "requester", "buyer", "plant_manager", "first_approver"])
            if current_status != "Draft":
                return redirect_with_msg(f"/requisitions/{req_id}", "Only draft requisitions can be submitted.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting First Approver", 1, now_iso(), req_id),
            )
            log("Submission", "Submitted", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Sent to first approver.")

        if action == "approve_first":
            require_role(user, ["admin", "first_approver"])
            if current_status != "Awaiting First Approver":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for first approver.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting Buyer Price Verification", 2, now_iso(), req_id),
            )
            log("First Approver", "Approved", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Approved and sent to buyer for price verification.")

        if action == "approve_buyer":
            require_role(user, ["admin", "buyer"])
            if current_status != "Awaiting Buyer Price Verification":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for buyer verification.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting Plant Manager Final Approval", 3, now_iso(), req_id),
            )
            log("Buyer Verification", "Approved", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Approved and sent to plant manager.")

        if action == "approve_final":
            require_role(user, ["admin", "plant_manager"])
            if current_status != "Awaiting Plant Manager Final Approval":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for final approval.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting Buyer PO Attachment", 4, now_iso(), req_id),
            )
            log("Plant Manager Final", "Approved", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Final approved. Buyer may attach PO.")

        if action == "attach_po":
            require_role(user, ["admin", "buyer"])
            if current_status != "Awaiting Buyer PO Attachment":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for PO attachment.", "error")
            po_file_path = ""
            po_upload = None
            return redirect_with_msg(f"/requisitions/{req_id}", "Use the PO attachment form on the requisition page.", "error")

        if action == "receive":
            require_role(user, ["admin", "receiver", "buyer", "plant_manager"])
            if current_status not in ("Ordered", "Partially Received"):
                return redirect_with_msg(f"/requisitions/{req_id}", "Requisition is not ready to receive.", "error")

            form = await request.form()
            received_total = 0
            any_partial = False
            rows = conn.execute("SELECT * FROM requisition_lines WHERE requisition_id = ?", (req_id,)).fetchall()
            for line in rows:
                key = f"received_qty_{line['id']}"
                raw = form.get(key, "")
                recv_qty = int(raw) if str(raw).strip() else line["qty"] - line["received_qty"]
                recv_qty = max(0, min(recv_qty, line["qty"] - line["received_qty"]))
                if recv_qty:
                    item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (line["part_no"],)).fetchone()
                    if item:
                        conn.execute(
                            "UPDATE inventory_items SET on_hand = on_hand + ?, updated_at = ? WHERE part_no = ?",
                            (recv_qty, now_iso(), line["part_no"]),
                        )
                    conn.execute(
                        "UPDATE requisition_lines SET received_qty = received_qty + ? WHERE id = ?",
                        (recv_qty, line["id"]),
                    )
                    received_total += recv_qty
                    if line["received_qty"] + recv_qty < line["qty"]:
                        any_partial = True

            packing_file_path = ""
            if "packing_file" in form:
                # file fields won't be in request.form
                pass

            upload = None
            # use request.stream handled by multipart, rely on form field names in the template
            # The template posts one file input named packing_file; read via request.form isn't enough,
            # so the route is dual purpose: file is handled in a separate receiving endpoint on POST from the template.
            # The actual upload is processed below using request._form won't work, so we load from the request scope.
            # To keep this route robust, we accept receipt without the file if not available here.
            if any_partial:
                new_status = "Partially Received"
            else:
                remaining = conn.execute(
                    "SELECT SUM(qty - received_qty) AS r FROM requisition_lines WHERE requisition_id = ?",
                    (req_id,),
                ).fetchone()["r"] or 0
                new_status = "Received" if remaining == 0 else "Partially Received"

            conn.execute(
                "UPDATE requisitions SET status=?, updated_at=?, received_at=?, received_by=? WHERE id=?",
                (new_status, now_iso(), now_iso(), user["full_name"], req_id),
            )
            log("Receiving", "Received", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Receipt saved and inventory updated.")

        if action == "reject":
            require_role(user, ["admin", "first_approver", "buyer", "plant_manager"])
            conn.execute("UPDATE requisitions SET status=?, updated_at=? WHERE id=?", ("Rejected", now_iso(), req_id))
            log("Rejection", "Rejected", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Requisition rejected.", "error")

    return redirect_with_msg(f"/requisitions/{req_id}", "Action not processed.", "error")


@app.post("/requisitions/{req_id}/attach-po")
async def attach_po(
    request: Request,
    req_id: int,
    po_number: str = Form(...),
    vendor: str = Form(""),
    po_file: UploadFile | None = File(default=None),
):
    user = require_login(request)
    require_role(user, ["admin", "buyer"])
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        if req["status"] != "Awaiting Buyer PO Attachment":
            return redirect_with_msg(f"/requisitions/{req_id}", "This requisition is not ready for PO attachment.", "error")
        file_path = ""
        if po_file and po_file.filename:
            ext = Path(po_file.filename).suffix.lower()
            safe_name = f"PO_{po_number}_{secrets.token_hex(4)}{ext}"
            dest = PO_DIR / safe_name
            content = await po_file.read()
            dest.write_bytes(content)
            file_path = str(dest.relative_to(BASE_DIR))
        conn.execute(
            """
            INSERT INTO purchase_orders (requisition_id, po_number, vendor, attachment, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(po_number) DO UPDATE SET
                vendor=excluded.vendor,
                attachment=excluded.attachment
            """,
            (req_id, po_number.strip(), vendor.strip(), file_path, user["full_name"], now_iso()),
        )
        conn.execute(
            "UPDATE requisitions SET po_number=?, status=?, updated_at=? WHERE id=?",
            (po_number.strip(), "Ordered", now_iso(), req_id),
        )
        conn.execute(
            """
            INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
            VALUES (?, 'Buyer PO Attachment', ?, 'PO Attached', ?, ?)
            """,
            (req_id, user["full_name"], vendor.strip(), now_iso()),
        )
    return redirect_with_msg(f"/requisitions/{req_id}", "PO attached and requisition marked Ordered.")


@app.post("/requisitions/{req_id}/receive")
async def receive_requisition(
    request: Request,
    req_id: int,
    packing_file: UploadFile | None = File(default=None),
    notes: str = Form(""),
):
    user = require_login(request)
    require_role(user, ["admin", "receiver", "buyer", "plant_manager"])
    form = await request.form()
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        if req["status"] not in ("Ordered", "Partially Received"):
            return redirect_with_msg(f"/requisitions/{req_id}", "Requisition is not ready to receive.", "error")
        file_path = ""
        if packing_file and packing_file.filename:
            ext = Path(packing_file.filename).suffix.lower()
            safe_name = f"Packing_{req['req_no']}_{secrets.token_hex(4)}{ext}"
            dest = PACKING_DIR / safe_name
            content = await packing_file.read()
            dest.write_bytes(content)
            file_path = str(dest.relative_to(BASE_DIR))

        rows = conn.execute("SELECT * FROM requisition_lines WHERE requisition_id = ?", (req_id,)).fetchall()
        any_partial = False
        for line in rows:
            key = f"received_qty_{line['id']}"
            raw = form.get(key, "")
            recv_qty = int(raw) if str(raw).strip() else (line["qty"] - line["received_qty"])
            recv_qty = max(0, min(recv_qty, line["qty"] - line["received_qty"]))
            if recv_qty:
                conn.execute(
                    "UPDATE inventory_items SET on_hand = on_hand + ?, updated_at = ? WHERE part_no = ?",
                    (recv_qty, now_iso(), line["part_no"]),
                )
                conn.execute(
                    "UPDATE requisition_lines SET received_qty = received_qty + ? WHERE id = ?",
                    (recv_qty, line["id"]),
                )
            if (line["received_qty"] + recv_qty) < line["qty"]:
                any_partial = True

        remaining = conn.execute(
            "SELECT SUM(qty - received_qty) AS r FROM requisition_lines WHERE requisition_id = ?",
            (req_id,),
        ).fetchone()["r"] or 0

        new_status = "Partially Received" if remaining > 0 else "Received"
        conn.execute(
            """
            INSERT INTO receipts (requisition_id, received_by, packing_list_file, notes, received_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (req_id, user["full_name"], file_path, notes.strip(), now_iso()),
        )
        conn.execute(
            """
            UPDATE requisitions
            SET status=?, updated_at=?, received_at=?, received_by=?, packing_list_file=?
            WHERE id=?
            """,
            (new_status, now_iso(), now_iso(), user["full_name"], file_path, req_id),
        )
        conn.execute(
            """
            INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
            VALUES (?, 'Receiving', ?, ?, ?, ?)
            """,
            (req_id, user["full_name"], "Received", notes.strip(), now_iso()),
        )
    return redirect_with_msg(f"/requisitions/{req_id}", "Receiving complete and inventory updated.")


@app.get("/purchase-orders", response_class=HTMLResponse)
def purchase_orders_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        pos = conn.execute(
            """
            SELECT po.*, r.req_no, r.requester, r.status
            FROM purchase_orders po
            JOIN requisitions r ON r.id = po.requisition_id
            ORDER BY datetime(po.created_at) DESC
            """
        ).fetchall()
    return templates.TemplateResponse(
        "purchase_orders.html",
        {
            "request": request,
            **auth_context(request),
            "pos": pos,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/receiving", response_class=HTMLResponse)
def receiving_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM requisitions WHERE status IN ('Ordered','Partially Received') ORDER BY datetime(updated_at) DESC"
        ).fetchall()
    return templates.TemplateResponse(
        "receiving.html",
        {
            "request": request,
            **auth_context(request),
            "rows": rows,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        top_items = conn.execute(
            """
            SELECT description, SUM(qty) AS total_qty, SUM(total_cost) AS total_cost
            FROM usage_log
            GROUP BY description
            ORDER BY total_qty DESC, description ASC
            LIMIT 20
            """
        ).fetchall()
        trips = compute_trips(conn.execute("SELECT employee, issued_at FROM usage_log ORDER BY employee, datetime(issued_at)").fetchall())
        low_stock = conn.execute("SELECT * FROM inventory_items WHERE on_hand <= min_level ORDER BY on_hand ASC").fetchall()
    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            **auth_context(request),
            "top_items": top_items,
            "trips": trips,
            "low_stock": low_stock,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, ["admin"])
    with db() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY username ASC").fetchall()
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            **auth_context(request),
            "users": users,
            "roles": ROLES,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/users/add")
def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
):
    user = require_login(request)
    require_role(user, ["admin"])
    if role not in ROLES:
        return redirect_with_msg("/users", "Invalid role.", "error")
    with db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (username.strip(), hash_password(password), full_name.strip(), role, now_iso()),
            )
        except sqlite3.IntegrityError:
            return redirect_with_msg("/users", "Username already exists.", "error")
    return redirect_with_msg("/users", "User added.")


@app.post("/users/{user_id}/toggle")
def toggle_user(request: Request, user_id: int):
    user = require_login(request)
    require_role(user, ["admin"])
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return redirect_with_msg("/users", "User not found.", "error")
        new_active = 0 if row["active"] else 1
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (new_active, user_id))
    return redirect_with_msg("/users", "User status updated.")


@app.post("/delete/cleanup")
def cleanup_test_data(request: Request):
    user = require_login(request)
    require_role(user, ["admin"])
    return redirect_with_msg("/", "Cleanup unavailable in this build.")


def file_link(path: str) -> str:
    return f"/file/{path.replace(os.sep, '/')}"


@app.get("/file/{file_path:path}")
def serve_file(file_path: str):
    abs_path = (BASE_DIR / file_path).resolve()
    if not str(abs_path).startswith(str(BASE_DIR.resolve())) or not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(abs_path))


if __name__ == "__main__":
    uvicorn.run("WH_ENTERPRISE_WEB:app", host="0.0.0.0", port=8000, reload=False)
