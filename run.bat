
{% extends "base.html" %}
{% block content %}
<div class="card">
  <h2>Purchase Orders</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>PO #</th><th>Req #</th><th>Requester</th><th>Vendor</th><th>Status</th><th>Attachment</th><th>Created</th></tr></thead>
      <tbody>
      {% for po in pos %}
        <tr>
          <td>{{ po.po_number }}</td>
          <td><a href="/requisitions/{{ po.requisition_id }}">{{ po.req_no }}</a></td>
          <td>{{ po.requester }}</td>
          <td>{{ po.vendor }}</td>
          <td><span class="status {{ po.status|lower|replace(' ','-') }}">{{ po.status }}</span></td>
          <td>{% if po.attachment %}<a href="/{{ po.attachment }}">Open</a>{% else %}—{% endif %}</td>
          <td>{{ po.created_at }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
