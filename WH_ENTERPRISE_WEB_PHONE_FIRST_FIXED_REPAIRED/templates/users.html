
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>User Administration</h2>
  <form method="post" action="/users/add">
    <div class="form-row three">
      <div><label>Username</label><input name="username" required></div>
      <div><label>Password</label><input name="password" type="password" required></div>
      <div><label>Full Name</label><input name="full_name" required></div>
    </div>
    <div class="form-row two">
      <div>
        <label>Role</label>
        <select name="role" required>
          {% for role in roles %}
            <option value="{{ role }}">{{ role.replace('_',' ').title() }}</option>
          {% endfor %}
        </select>
      </div>
      <div style="display:flex; align-items:end;">
        <input type="submit" class="btn primary" value="Add User">
      </div>
    </div>
  </form>
</div>

<div class="card">
  <h3>Current Users</h3>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Username</th><th>Full Name</th><th>Role</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>
      {% for u in users %}
        <tr>
          <td>{{ u.username }}</td>
          <td>{{ u.full_name }}</td>
          <td>{{ u.role }}</td>
          <td>{{ "Active" if u.active else "Inactive" }}</td>
          <td>
            <form method="post" action="/users/{{ u.id }}/toggle">
              <button class="btn" type="submit">{% if u.active %}Deactivate{% else %}Activate{% endif %}</button>
            </form>
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
