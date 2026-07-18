"""
MCI5 Critical Roles Kiosk - Backend Server
Flask + JSON persistence on ~/shared + CRM dashboard
Port: 5001
"""

import os
import json
import csv
import io
import uuid
import logging
import subprocess
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response

# ── Slack notifier path ───────────────────────────────────────────────────────
PYTHON = "/home/robiatal/.local/share/mise/shims/python3"
NOTIFY = os.path.expanduser("~/critical-roles-kiosk/slack_notify.py")

def slack_notify(ntype, login, **kwargs):
    """Fire-and-forget Slack notification."""
    try:
        cmd = [PYTHON, NOTIFY, "--type", ntype, "--login", login]
        for k, v in kwargs.items():
            cmd += [f"--{k}", str(v)]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.error(f"Slack notify dispatch failed: {e}")

# ── Paths ─────────────────────────────────────────────────────────────────────
APP_DIR          = os.path.expanduser("~/critical-roles-kiosk")
LOG_FILE         = os.path.join(APP_DIR, "kiosk.log")
SUBMISSIONS_FILE = os.path.expanduser("~/shared/crk_submissions.json")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="assets",
    static_url_path="/assets"
)

# Disable static file caching so CSS/JS changes reflect immediately
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"]        = "no-cache"
        response.headers["Expires"]       = "0"
    return response

# ── Constants ─────────────────────────────────────────────────────────────────
STATUSES = ["New", "Contacted", "Approved", "Scheduled", "Training Complete", "Archived"]
ROLES    = [
    "Problem Solve", "Learning Ambassador", "GTDR Certification",
    "Sort Slide", "Crossdock", "Shuttle Dump", "Fluid Unloader",
    "Waterspider", "Smalls", "Flow Scanner", "Container Stager / Container Loader"
]

# ── Data helpers ──────────────────────────────────────────────────────────────
def load_submissions():
    if not os.path.exists(SUBMISSIONS_FILE):
        return []
    with open(SUBMISSIONS_FILE, "r") as f:
        return json.load(f)

def save_submissions(data):
    with open(SUBMISSIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def find_submission(submissions, sid):
    return next((s for s in submissions if s.get("id") == sid), None)

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── Routes — Kiosk ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    try:
        data  = request.get_json()
        login = data.get("login", "").strip()
        roles = data.get("roles", [])
        upt   = data.get("upt", "").strip()

        errors = []
        if not login: errors.append("Amazon login is required.")
        if not roles: errors.append("Please select at least one role.")
        if not upt:   errors.append("UPT balance is required.")
        if errors:
            return jsonify({"success": False, "errors": errors}), 400

        entry = {
            "id":           str(uuid.uuid4())[:8],
            "timestamp":    now(),
            "login":        login,
            "upt":          upt,
            "roles":        roles,
            "status":       "New",
            "notes":        "",
            "flag":         False,
            "updated_at":   now(),
            "updated_by":   ""
        }
        submissions = load_submissions()
        submissions.append(entry)
        save_submissions(submissions)
        log.info(f"New submission — {login} | upt={upt} | roles={roles}")

        # Fire Slack new submission alert (fire-and-forget)
        slack_notify("new", login=login, upt=upt, roles=",".join(roles))

        return jsonify({"success": True, "message": "Your request has been submitted! Leadership will follow up with you soon. 🐂"})

    except Exception as e:
        log.error(f"Submit error: {e}")
        return jsonify({"success": False, "errors": ["Something went wrong. Please try again or see a manager."]}), 500


# ── Routes — CRM Dashboard ────────────────────────────────────────────────────
@app.route("/submissions")
def submissions_dashboard():
    submissions = load_submissions()

    # ── Stats ────────────────────────────────────────────────────────────────
    total      = len(submissions)
    active     = [s for s in submissions if s.get("status") != "Archived"]
    stat_new   = sum(1 for s in active if s.get("status") == "New")
    stat_prog  = sum(1 for s in active if s.get("status") in ["Contacted", "Approved", "Scheduled"])
    stat_done  = sum(1 for s in active if s.get("status") == "Training Complete")
    stat_flag  = sum(1 for s in active if s.get("flag"))
    stat_sla   = sum(1 for s in active if s.get("sla_breached") and s.get("status") == "New")

    # Role interest counts (active only)
    role_counts = {r: 0 for r in ROLES}
    for s in active:
        for r in s.get("roles", []):
            if r in role_counts:
                role_counts[r] += 1
    role_counts_sorted = sorted(role_counts.items(), key=lambda x: x[1], reverse=True)
    max_role_count = max((v for _, v in role_counts_sorted), default=1)

    # Status badge colors
    status_colors = {
        "New":               "#6c757d",
        "Contacted":         "#0d6efd",
        "Approved":          "#198754",
        "Scheduled":         "#fd7e14",
        "Training Complete": "#6f42c1",
        "Archived":          "#adb5bd"
    }

    # Build table rows (newest first, archived last)
    def sort_key(s):
        archived = 1 if s.get("status") == "Archived" else 0
        return (archived, s.get("timestamp", ""))

    sorted_subs = sorted(submissions, key=sort_key, reverse=True)
    sorted_subs_json = json.dumps(sorted_subs)

    rows_html = ""
    for s in sorted_subs:
        sid        = s.get("id", "")
        status     = s.get("status", "New")
        color      = status_colors.get(status, "#6c757d")
        flag       = s.get("flag", False)
        sla_breach = s.get("sla_breached", False) and status == "New"
        notes      = s.get("notes", "").replace('"', '&quot;').replace("'", "&#39;")
        roles_str  = ", ".join(s.get("roles", []))
        updated    = s.get("updated_at", "")
        updated_by = s.get("updated_by", "")
        updated_info = f"{updated}" + (f" · {updated_by}" if updated_by else "")
        opacity    = "opacity:0.45;" if status == "Archived" else ""
        row_border = "border-left:4px solid #dc3545;" if sla_breach else ""
        sla_badge  = ' <span style="background:#dc3545;color:#fff;font-size:10px;padding:2px 6px;border-radius:8px;font-weight:bold;">⚠️ SLA</span>' if sla_breach else ""

        status_opts = "".join(
            f'<option value="{st}" {"selected" if st == status else ""}>{st}</option>'
            for st in STATUSES
        )

        rows_html += f"""
        <tr id="row-{sid}" style="{opacity}{row_border}" data-status="{status}" data-login="{s.get('login','').lower()}" data-upt="{s.get('upt','0')}" data-timestamp="{s.get('timestamp','')}">
          <td style="text-align:center;">
            <button onclick="toggleFlag('{sid}', this)" class="flag-btn {'flagged' if flag else ''}" title="Flag for follow-up">
              {'🚩' if flag else '⚑'}
            </button>
          </td>
          <td style="font-size:12px;color:#666;">{s.get('timestamp','')[:16]}</td>
          <td><strong>{s.get('login','')}</strong>{sla_badge}</td>
          <td style="text-align:center;">{s.get('upt','')}</td>
          <td style="font-size:12px;">{roles_str}</td>
          <td>
            <select onchange="updateStatus('{sid}', this.value)" class="status-select" style="background:{color};color:#fff;border:none;padding:4px 8px;border-radius:12px;font-size:12px;font-weight:bold;cursor:pointer;">
              {status_opts}
            </select>
          </td>
          <td>
            <div style="display:flex;gap:6px;align-items:center;">
              <input type="text" id="notes-{sid}" value="{notes if notes else ''}" placeholder="Add notes... e.g. Schedule for next week" class="notes-input" style="flex:1;padding:5px 8px;border:1px solid #ddd;border-radius:6px;font-size:12px;">
              <button onclick="saveNotes('{sid}')" class="save-btn" title="Save notes">💾</button>
            </div>
            <div id="updated-{sid}" style="font-size:10px;color:#999;margin-top:3px;">{updated_info}</div>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MCI5 Kiosk — CRM Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: Arial, sans-serif; background: #f0f2f5; min-height: 100vh; }}

    /* Header */
    .top-bar {{ background: #183f7a; padding: 16px 28px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }}
    .top-bar h1 {{ color: #fff; font-size: 20px; margin: 0; }}
    .top-bar .actions {{ display: flex; gap: 10px; align-items: center; }}
    .btn {{ padding: 8px 16px; border-radius: 8px; border: none; font-size: 13px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; }}
    .btn-export {{ background: #28a745; color: #fff; }}
    .btn-kiosk  {{ background: rgba(255,255,255,0.15); color: #fff; }}
    .btn-export:hover {{ background: #218838; }}
    .btn-kiosk:hover  {{ background: rgba(255,255,255,0.25); }}

    /* Stats cards */
    .stats {{ display: flex; gap: 14px; padding: 20px 28px 0; flex-wrap: wrap; }}
    .stat-card {{ background: #fff; border-radius: 10px; padding: 16px 22px; flex: 1; min-width: 120px; box-shadow: 0 1px 4px rgba(0,0,0,.08); border-left: 4px solid #183f7a; }}
    .stat-card.green  {{ border-color: #28a745; }}
    .stat-card.orange {{ border-color: #fd7e14; }}
    .stat-card.purple {{ border-color: #6f42c1; }}
    .stat-card.red    {{ border-color: #dc3545; }}
    .stat-num  {{ font-size: 32px; font-weight: 900; color: #183f7a; line-height: 1; }}
    .stat-card.green  .stat-num {{ color: #28a745; }}
    .stat-card.orange .stat-num {{ color: #fd7e14; }}
    .stat-card.purple .stat-num {{ color: #6f42c1; }}
    .stat-card.red    .stat-num {{ color: #dc3545; }}
    .stat-label {{ font-size: 12px; color: #888; margin-top: 4px; text-transform: uppercase; letter-spacing: .5px; }}

    /* Role chart */
    .chart-section {{ margin: 20px 28px 0; background: #fff; border-radius: 10px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .chart-section h3 {{ font-size: 14px; color: #183f7a; margin-bottom: 14px; text-transform: uppercase; letter-spacing: .5px; }}
    .chart-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
    .chart-label {{ font-size: 12px; color: #555; width: 260px; flex-shrink: 0; text-align: right; }}
    .chart-bar-wrap {{ flex: 1; background: #f0f2f5; border-radius: 4px; height: 18px; overflow: hidden; }}
    .chart-bar {{ height: 100%; background: #183f7a; border-radius: 4px; transition: width .3s; }}
    .chart-count {{ font-size: 12px; font-weight: bold; color: #183f7a; width: 24px; }}

    /* Filters */
    .filters {{ margin: 20px 28px 0; background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }}
    .filter-group {{ display: flex; flex-direction: column; gap: 4px; }}
    .filter-group label {{ font-size: 11px; font-weight: bold; color: #888; text-transform: uppercase; letter-spacing: .4px; }}
    .filter-group input, .filter-group select {{ padding: 7px 10px; border: 1px solid #ddd; border-radius: 7px; font-size: 13px; min-width: 140px; }}
    .btn-reset {{ background: #6c757d; color: #fff; padding: 7px 14px; border-radius: 7px; border: none; font-size: 13px; cursor: pointer; align-self: flex-end; }}
    .btn-reset:hover {{ background: #5a6268; }}

    /* Table */
    .table-wrap {{ margin: 16px 28px 28px; background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ background: #183f7a; color: #fff; padding: 11px 14px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .4px; cursor: pointer; user-select: none; white-space: nowrap; }}
    th:hover {{ background: #1a4a99; }}
    td {{ padding: 10px 14px; border-bottom: 1px solid #f0f0f0; font-size: 13px; vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f7f9fc; }}
    .no-results {{ text-align: center; padding: 50px; color: #999; font-size: 15px; }}

    /* Interactive elements */
    .flag-btn {{ background: none; border: none; font-size: 16px; cursor: pointer; padding: 2px 6px; border-radius: 4px; transition: transform .1s; }}
    .flag-btn:hover {{ transform: scale(1.2); }}
    .flag-btn.flagged {{ filter: none; }}
    .status-select {{ outline: none; }}
    .notes-input {{ outline: none; transition: border-color .2s; }}
    .notes-input:focus {{ border-color: #183f7a; }}
    .save-btn {{ background: #183f7a; color: #fff; border: none; border-radius: 6px; padding: 5px 8px; cursor: pointer; font-size: 13px; }}
    .save-btn:hover {{ background: #1a4a99; }}
    .toast {{ position: fixed; bottom: 24px; right: 24px; background: #28a745; color: #fff; padding: 12px 20px; border-radius: 8px; font-size: 14px; font-weight: bold; display: none; z-index: 9999; box-shadow: 0 4px 12px rgba(0,0,0,.2); }}
  </style>
</head>
<body>

  <!-- Header -->
  <div class="top-bar">
    <h1>🐂 MCI5 Critical Roles — CRM Dashboard</h1>
    <div class="actions">
      <a href="/export-csv" class="btn btn-export">⬇ Export CSV</a>
      <a href="/" class="btn btn-kiosk">← Kiosk</a>
    </div>
  </div>

  <!-- Stats -->
  <div class="stats">
    <div class="stat-card">
      <div class="stat-num">{total}</div>
      <div class="stat-label">Total Submissions</div>
    </div>
    <div class="stat-card red">
      <div class="stat-num">{stat_new}</div>
      <div class="stat-label">New</div>
    </div>
    <div class="stat-card orange">
      <div class="stat-num">{stat_prog}</div>
      <div class="stat-label">In Progress</div>
    </div>
    <div class="stat-card purple">
      <div class="stat-num">{stat_done}</div>
      <div class="stat-label">Training Complete</div>
    </div>
    <div class="stat-card green">
      <div class="stat-num">{stat_flag}</div>
      <div class="stat-label">🚩 Flagged</div>
    </div>
    <div class="stat-card red">
      <div class="stat-num">{stat_sla}</div>
      <div class="stat-label">⚠️ SLA Breach</div>
    </div>
  </div>

  <!-- Role Interest Chart -->
  <div class="chart-section">
    <h3>Role Interest (Active Submissions)</h3>
    {''.join(f'''<div class="chart-row">
      <div class="chart-label">{r}</div>
      <div class="chart-bar-wrap"><div class="chart-bar" style="width:{round(c/max_role_count*100) if max_role_count else 0}%"></div></div>
      <div class="chart-count">{c}</div>
    </div>''' for r, c in role_counts_sorted)}
  </div>

  <!-- Filters -->
  <div class="filters">
    <div class="filter-group">
      <label>Search Login</label>
      <input type="text" id="f-search" placeholder="e.g. jdoe" oninput="applyFilters()">
    </div>
    <div class="filter-group">
      <label>Status</label>
      <select id="f-status" onchange="applyFilters()">
        <option value="">All Statuses</option>
        {''.join(f'<option value="{s}">{s}</option>' for s in STATUSES)}
      </select>
    </div>
    <div class="filter-group">
      <label>Role</label>
      <select id="f-role" onchange="applyFilters()">
        <option value="">All Roles</option>
        {''.join(f'<option value="{r}">{r}</option>' for r in ROLES)}
      </select>
    </div>
    <div class="filter-group">
      <label>Min UPT</label>
      <input type="number" id="f-upt-min" placeholder="0" min="0" oninput="applyFilters()" style="width:90px;">
    </div>
    <div class="filter-group">
      <label>Max UPT</label>
      <input type="number" id="f-upt-max" placeholder="any" min="0" oninput="applyFilters()" style="width:90px;">
    </div>
    <div class="filter-group">
      <label>Sort By</label>
      <select id="f-sort" onchange="applyFilters()">
        <option value="date-desc">Date (Newest)</option>
        <option value="date-asc">Date (Oldest)</option>
        <option value="login-asc">Login (A–Z)</option>
        <option value="upt-desc">UPT (High–Low)</option>
        <option value="upt-asc">UPT (Low–High)</option>
      </select>
    </div>
    <button class="btn-reset" onclick="resetFilters()">Reset</button>
  </div>

  <!-- Table -->
  <div class="table-wrap">
    <table id="crm-table">
      <thead>
        <tr>
          <th style="width:40px;">🚩</th>
          <th>Date</th>
          <th>Login</th>
          <th>UPT</th>
          <th>Roles</th>
          <th>Status</th>
          <th>Notes / Last Updated</th>
        </tr>
      </thead>
      <tbody id="table-body">
        {rows_html if rows_html else '<tr><td colspan="7" class="no-results">No submissions yet.</td></tr>'}
      </tbody>
    </table>
  </div>

  <!-- Toast -->
  <div class="toast" id="toast"></div>

  <script>
    const ALL_DATA = {sorted_subs_json};

    function showToast(msg, color) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.background = color || '#28a745';
      t.style.display = 'block';
      setTimeout(() => t.style.display = 'none', 2500);
    }}

    async function updateStatus(sid, newStatus) {{
      const updatedBy = prompt('Your login (for audit trail):', '') || '';
      const res = await fetch('/api/update', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{id: sid, status: newStatus, updated_by: updatedBy}})
      }});
      const data = await res.json();
      if (data.success) {{
        const row = document.getElementById('row-' + sid);
        row.setAttribute('data-status', newStatus);
        row.style.opacity = newStatus === 'Archived' ? '0.45' : '1';
        document.getElementById('updated-' + sid).textContent = data.updated_at + (updatedBy ? ' · ' + updatedBy : '');
        showToast('Status updated: ' + newStatus);
      }} else {{
        showToast('Error saving status', '#dc3545');
      }}
    }}

    async function saveNotes(sid) {{
      const notes = document.getElementById('notes-' + sid).value;
      const updatedBy = '';
      const res = await fetch('/api/update', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{id: sid, notes: notes, updated_by: updatedBy}})
      }});
      const data = await res.json();
      if (data.success) {{
        document.getElementById('updated-' + sid).textContent = data.updated_at;
        showToast('Notes saved 💾');
      }} else {{
        showToast('Error saving notes', '#dc3545');
      }}
    }}

    async function toggleFlag(sid, btn) {{
      const res = await fetch('/api/update', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{id: sid, toggle_flag: true}})
      }});
      const data = await res.json();
      if (data.success) {{
        btn.textContent = data.flagged ? '🚩' : '⚑';
        btn.classList.toggle('flagged', data.flagged);
        showToast(data.flagged ? 'Flagged for follow-up 🚩' : 'Flag removed');
      }}
    }}

    function applyFilters() {{
      const search  = document.getElementById('f-search').value.toLowerCase();
      const status  = document.getElementById('f-status').value;
      const role    = document.getElementById('f-role').value;
      const uptMin  = parseFloat(document.getElementById('f-upt-min').value) || 0;
      const uptMax  = parseFloat(document.getElementById('f-upt-max').value) || Infinity;
      const sortBy  = document.getElementById('f-sort').value;

      let rows = Array.from(document.querySelectorAll('#table-body tr[id]'));

      rows.forEach(row => {{
        const rowLogin  = row.getAttribute('data-login') || '';
        const rowStatus = row.getAttribute('data-status') || '';
        const rowUpt    = parseFloat(row.getAttribute('data-upt')) || 0;
        const rolesCell = row.querySelectorAll('td')[4]?.textContent || '';

        const matchSearch = !search  || rowLogin.includes(search);
        const matchStatus = !status  || rowStatus === status;
        const matchRole   = !role    || rolesCell.includes(role);
        const matchUpt    = rowUpt >= uptMin && rowUpt <= uptMax;

        row.style.display = (matchSearch && matchStatus && matchRole && matchUpt) ? '' : 'none';
      }});

      // Sort visible rows
      const tbody = document.getElementById('table-body');
      const visible = rows.filter(r => r.style.display !== 'none');
      visible.sort((a, b) => {{
        if (sortBy === 'date-desc') return b.getAttribute('data-timestamp').localeCompare(a.getAttribute('data-timestamp'));
        if (sortBy === 'date-asc')  return a.getAttribute('data-timestamp').localeCompare(b.getAttribute('data-timestamp'));
        if (sortBy === 'login-asc') return a.getAttribute('data-login').localeCompare(b.getAttribute('data-login'));
        if (sortBy === 'upt-desc')  return (parseFloat(b.getAttribute('data-upt'))||0) - (parseFloat(a.getAttribute('data-upt'))||0);
        if (sortBy === 'upt-asc')   return (parseFloat(a.getAttribute('data-upt'))||0) - (parseFloat(b.getAttribute('data-upt'))||0);
        return 0;
      }});
      visible.forEach(r => tbody.appendChild(r));
    }}

    function resetFilters() {{
      document.getElementById('f-search').value  = '';
      document.getElementById('f-status').value  = '';
      document.getElementById('f-role').value    = '';
      document.getElementById('f-upt-min').value = '';
      document.getElementById('f-upt-max').value = '';
      document.getElementById('f-sort').value    = 'date-desc';
      applyFilters();
    }}
  </script>
</body>
</html>"""


# ── API — Update submission ───────────────────────────────────────────────────
@app.route("/api/update", methods=["POST"])
def api_update():
    try:
        data        = request.get_json()
        sid         = data.get("id")
        submissions = load_submissions()
        entry       = find_submission(submissions, sid)

        if not entry:
            return jsonify({"success": False, "error": "Not found"}), 404

        if "status"      in data: entry["status"]     = data["status"]
        if "notes"       in data: entry["notes"]      = data["notes"]
        if "updated_by"  in data: entry["updated_by"] = data["updated_by"]
        if data.get("toggle_flag"):
            entry["flag"] = not entry.get("flag", False)

        entry["updated_at"] = now()
        save_submissions(submissions)

        return jsonify({
            "success":    True,
            "updated_at": entry["updated_at"],
            "flagged":    entry.get("flag", False)
        })
    except Exception as e:
        log.error(f"API update error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Export CSV ────────────────────────────────────────────────────────────────
@app.route("/export-csv")
def export_csv():
    submissions = load_submissions()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "Login", "UPT", "Roles", "Status", "Notes", "Updated At", "Updated By", "Flagged"])
    for s in submissions:
        writer.writerow([
            s.get("id", ""),
            s.get("timestamp", ""),
            s.get("login", ""),
            s.get("upt", ""),
            " | ".join(s.get("roles", [])),
            s.get("status", ""),
            s.get("notes", ""),
            s.get("updated_at", ""),
            s.get("updated_by", ""),
            "Yes" if s.get("flag") else "No"
        ])
    filename = f"mci5_crk_submissions_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── Health ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    subs = load_submissions()
    return jsonify({
        "status":      "ok",
        "service":     "MCI5 Critical Roles Kiosk",
        "submissions": len(subs),
        "new":         sum(1 for s in subs if s.get("status") == "New")
    }), 200


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("Starting MCI5 Critical Roles Kiosk on port 5001...")
    app.run(host="0.0.0.0", port=5001, debug=False)
