
:root {
  --bg: #111;
  --card: #1f1f1f;
  --card-2: #262626;
  --text: #f3f3f3;
  --muted: #bcbcbc;
  --accent: #f26522;
  --accent-2: #ff8a4c;
  --success: #2ecc71;
  --warning: #f1c40f;
  --danger: #e74c3c;
  --info: #3498db;
  --border: rgba(255,255,255,0.08);
  --shadow: 0 10px 30px rgba(0,0,0,0.25);
  --radius: 18px;
  --nav-height: 70px;
}

body.theme-dark-modern { --bg:#111111; --card:#1e1e1e; --card-2:#2a2a2a; --text:#f5f5f5; --muted:#cfcfcf; --accent:#f26522; --accent-2:#ff9b67; --border:rgba(255,255,255,0.08); }
body.theme-light-modern { --bg:#f4f4f4; --card:#ffffff; --card-2:#ffffff; --text:#111111; --muted:#444444; --accent:#f26522; --accent-2:#ff9b67; --border:rgba(0,0,0,0.08); }
body.theme-florida-state { --bg:#782F40; --card:#CEB888; --card-2:#e5d7b6; --text:#ffffff; --muted:#f5f5f5; --accent:#CEB888; --accent-2:#f0e0bc; --border:rgba(255,255,255,0.12); }
body.theme-ohio-state { --bg:#BB0000; --card:#666666; --card-2:#7a7a7a; --text:#ffffff; --muted:#f1f1f1; --accent:#ffffff; --accent-2:#ffefef; --border:rgba(255,255,255,0.12); }
body.theme-patriots { --bg:#0A2342; --card:#C60C30; --card-2:#d43a56; --text:#ffffff; --muted:#f3f3f3; --accent:#ffffff; --accent-2:#d6e4ff; --border:rgba(255,255,255,0.12); }
body.theme-cowboys { --bg:#041E42; --card:#869397; --card-2:#9aa6aa; --text:#ffffff; --muted:#f5f5f5; --accent:#ffffff; --accent-2:#eff6ff; --border:rgba(255,255,255,0.12); }
body.theme-cardinals { --bg:#97233F; --card:#000000; --card-2:#111111; --text:#ffffff; --muted:#f2f2f2; --accent:#FFB612; --accent-2:#ffd66e; --border:rgba(255,255,255,0.12); }

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; min-height: 100%; background: var(--bg); color: var(--text); font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; }
body { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
button, input, select, textarea { font: inherit; }
.container { max-width: 1500px; margin: 0 auto; padding: 16px; padding-bottom: calc(16px + env(safe-area-inset-bottom)); }
.topbar {
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:12px 16px; background: var(--card); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 50;
  padding-top: calc(12px + env(safe-area-inset-top));
}
.brand { display:flex; align-items:center; gap:12px; font-weight:800; letter-spacing:0.3px; }
.brand img { width:52px; height:52px; object-fit:contain; border-radius:12px; background: rgba(255,255,255,0.05); padding:4px; }
.navlinks { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.navlinks a, .navlinks button, .btn, .chip, .pill, input[type="submit"] {
  display:inline-flex; align-items:center; justify-content:center; min-height: 44px;
  border:1px solid var(--border); background: var(--card-2); color: var(--text);
  padding:10px 14px; border-radius:14px; cursor:pointer; font-weight:700;
  box-shadow:none; transition: all .15s ease;
}
.navlinks a:hover, .btn:hover, .chip:hover, input[type="submit"]:hover { transform: translateY(-1px); border-color: var(--accent); }
.nav-right { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
select, input, textarea {
  width:100%; padding:12px 12px; min-height: 46px; border-radius:14px; border:1px solid var(--border);
  background: var(--card-2); color: var(--text); outline:none;
}
input, textarea { box-shadow: inset 0 0 0 1px transparent; }
textarea { min-height: 100px; resize: vertical; }
label { display:block; font-size: 0.92rem; margin-bottom:6px; color: var(--muted); }
.page-grid { display:grid; grid-template-columns: 280px 1fr; gap:16px; margin-top: 16px; align-items:start; }
.page-grid.no-sidebar { grid-template-columns: 1fr; }
.sidebar, .card {
  background: var(--card); border:1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow);
}
.sidebar { padding:16px; height: fit-content; position: sticky; top: 92px; }
.sidebar h3 { margin-top:0; margin-bottom:12px; }
.sidebar a { display:block; padding:12px 12px; border-radius:14px; background: transparent; border:1px solid transparent; margin-bottom:8px; }
.sidebar a:hover { background: var(--card-2); border-color: var(--border); }
.content { min-width: 0; }
.card { padding:16px; margin-bottom:16px; }
.card h2, .card h3 { margin-top:0; }
.grid { display:grid; gap:14px; }
.grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.grid.cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.stat {
  padding:18px; border-radius:18px; background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent);
  border:1px solid var(--border);
}
.stat .label { color: var(--muted); font-size: 0.92rem; }
.stat .value { font-size: clamp(1.4rem, 5vw, 2.25rem); font-weight: 900; margin-top:8px; }
.flash { padding: 12px 14px; border-radius: 14px; margin-bottom: 16px; font-weight: 700; }
.flash.success { background: rgba(46,204,113,0.14); border: 1px solid rgba(46,204,113,0.35); }
.flash.error { background: rgba(231,76,60,0.14); border: 1px solid rgba(231,76,60,0.35); }
.flash.info { background: rgba(52,152,219,0.14); border: 1px solid rgba(52,152,219,0.35); }
.table-wrap { overflow-x:auto; -webkit-overflow-scrolling: touch; }
table { width:100%; border-collapse: collapse; }
th, td { padding: 11px 10px; border-bottom: 1px solid var(--border); text-align:left; vertical-align: top; }
th { color: var(--muted); font-size: 0.88rem; text-transform: uppercase; letter-spacing: 0.05em; }
tr:hover td { background: rgba(255,255,255,0.02); }
.status {
  display:inline-flex; align-items:center; padding:7px 10px; border-radius: 999px; font-size:0.82rem; font-weight:800;
  border:1px solid var(--border); white-space: nowrap;
}
.status.draft { background: rgba(255,255,255,0.06); }
.status.awaiting-first-approver { background: rgba(52,152,219,0.16); }
.status.awaiting-buyer-price-verification { background: rgba(241,196,15,0.16); }
.status.awaiting-plant-manager-final-approval { background: rgba(155,89,182,0.16); }
.status.awaiting-buyer-po-attachment { background: rgba(243,156,18,0.16); }
.status.ordered { background: rgba(46,204,113,0.16); }
.status.partially-received { background: rgba(241,196,15,0.2); }
.status.received { background: rgba(46,204,113,0.2); }
.status.rejected { background: rgba(231,76,60,0.2); }
.bar { height: 12px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; margin: 6px 0 0; }
.bar > span { display:block; height:100%; background: var(--accent); border-radius: 999px; }
.small { color: var(--muted); font-size: 0.9rem; }
.form-row { display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:12px; margin-bottom:12px; }
.form-row.two { grid-template-columns: repeat(2, minmax(0,1fr)); }
.form-row.three { grid-template-columns: repeat(3, minmax(0,1fr)); }
.form-actions { display:flex; gap:10px; flex-wrap:wrap; margin-top: 12px; }
.btn.primary, input[type="submit"].primary { background: var(--accent); color:#fff; border-color: transparent; }
.btn.danger { background: var(--danger); color:#fff; border-color: transparent; }
.btn.success { background: var(--success); color:#fff; border-color: transparent; }
.btn.info { background: var(--info); color:#fff; border-color: transparent; }
.file-drop {
  border: 2px dashed var(--border); border-radius: 16px; padding: 14px; background: rgba(255,255,255,0.03);
}
.file-drop.dragover { border-color: var(--accent); background: rgba(242,101,34,0.10); }
.timeline { display:flex; flex-direction:column; gap:10px; }
.timeline-item {
  padding: 12px 14px; border-left: 4px solid var(--accent); background: rgba(255,255,255,0.03); border-radius: 12px;
}
.notice { padding: 12px 14px; border-radius: 14px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); margin-bottom: 14px; }
.footer { margin-top: 24px; color: var(--muted); text-align:center; padding: 14px 0 28px; }
.hidden { display:none; }
.logo-banner { width:56px; height:56px; object-fit:contain; }
.mobile-nav {
  display:none;
}
.desktop-nav { display:flex; }

@media (max-width: 1000px) {
  .page-grid, .grid.cols-4, .grid.cols-3, .grid.cols-2, .form-row, .form-row.two, .form-row.three { grid-template-columns: 1fr; }
  .sidebar { position: static; }
  .topbar { flex-direction: column; align-items:flex-start; }
  .desktop-nav { display:none; }
  .mobile-nav {
    display:grid;
    grid-template-columns: repeat(3, 1fr);
    gap:8px;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 45;
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
    background: var(--card);
    border-top: 1px solid var(--border);
    box-shadow: 0 -8px 24px rgba(0,0,0,0.24);
  }
  .mobile-nav a {
    display:flex;
    justify-content:center;
    align-items:center;
    min-height: 44px;
    text-align:center;
    padding: 10px 8px;
    border-radius: 14px;
    background: var(--card-2);
    color: var(--text);
    border: 1px solid var(--border);
    font-size: 0.9rem;
    font-weight: 800;
  }
  .mobile-nav a.active {
    border-color: var(--accent);
    color: var(--accent);
  }
  .container { padding-bottom: calc(100px + env(safe-area-inset-bottom)); }
}

@media (max-width: 640px) {
  .brand img { width:46px; height:46px; }
  .topbar { padding: 12px; }
  .container { padding: 12px; padding-bottom: calc(100px + env(safe-area-inset-bottom)); }
  .card { padding: 14px; }
  .mobile-nav { grid-template-columns: repeat(2, 1fr); }
}
