
document.addEventListener("DOMContentLoaded", () => {
  const currentPath = (document.body.dataset.path || window.location.pathname || "/").replace(/\/$/, "") || "/";
  document.querySelectorAll(".mobile-nav a, .desktop-nav a").forEach(a => {
    const href = (a.getAttribute("href") || "").replace(/\/$/, "") || "/";
    if (href === currentPath) a.classList.add("active");
  });

  const addLineBtn = document.getElementById("addLineBtn");
  const lineTable = document.getElementById("lineTable");
  if (addLineBtn && lineTable) {
    addLineBtn.addEventListener("click", () => {
      const tbody = lineTable.querySelector("tbody");
      const row = tbody.querySelector(".line-row");
      const clone = row.cloneNode(true);
      clone.querySelectorAll("input").forEach(inp => {
        if (inp.name === "qty") inp.value = "1";
        else if (inp.name === "unit_cost") inp.value = "0";
        else inp.value = "";
      });
      tbody.appendChild(clone);
      bindLineRow(clone);
    });
    bindLineRow(document.querySelector(".line-row"));
  }

  function bindLineRow(row) {
    if (!row) return;
    const part = row.querySelector(".part-input");
    const desc = row.querySelector(".desc-input");
    const remove = row.querySelector(".remove-line");
    if (remove) {
      remove.addEventListener("click", () => {
        const tbody = row.parentElement;
        if (tbody.querySelectorAll(".line-row").length > 1) row.remove();
      });
    }
    if (part) {
      part.addEventListener("change", async () => {
        if (!part.value) return;
        try {
          const res = await fetch(`/api/items/${encodeURIComponent(part.value)}`);
          const data = await res.json();
          if (data.found) {
            if (desc && !desc.value) desc.value = data.description;
            const costInput = row.querySelector('input[name="unit_cost"]');
            if (costInput && (!costInput.value || costInput.value === "0")) costInput.value = data.unit_cost;
          }
        } catch (e) {}
      });
    }
  }

  document.querySelectorAll(".dropzone").forEach(zone => {
    const input = zone.querySelector(".file-input");
    if (!input) return;

    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        input.files = e.dataTransfer.files;
      }
    });
    zone.addEventListener("click", () => input.click());
  });
});
