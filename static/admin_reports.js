const savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
const reportsList = document.getElementById("reportsList");

function logout() {
  localStorage.removeItem("catalogo_user");
  window.location.href = "/auth-page";
}

function ensureAdmin() {
  if (!savedUser || !savedUser.is_admin) {
    alert("Acesso restrito ao administrador.");
    window.location.href = "/search-page";
    return false;
  }
  return true;
}

function renderReports(items) {
  reportsList.innerHTML = "";

  if (!items.length) {
    reportsList.innerHTML = `<div class="muted">Nenhuma denúncia encontrada.</div>`;
    return;
  }

  const groupedByUser = {};

  items.forEach(item => {
    const userKey = item.reported_user_id || "unknown_user";
    const adKey = item.ad_id || "unknown_ad";

    if (!groupedByUser[userKey]) {
      groupedByUser[userKey] = {
        userId: item.reported_user_id,
        userName: item.reported_user_name || "Não informado",
        userEmail: item.reported_user_email || "Não informado",
        reportsCount: 0,
        ads: {}
      };
    }

    if (!groupedByUser[userKey].ads[adKey]) {
      groupedByUser[userKey].ads[adKey] = {
        adId: item.ad_id,
        adTitle: item.ad_title || "Anúncio sem título",
        reports: []
      };
    }

    groupedByUser[userKey].reportsCount += 1;
    groupedByUser[userKey].ads[adKey].reports.push(item);
  });

  Object.values(groupedByUser).forEach((userGroup, index) => {
    const userBlock = document.createElement("div");
    userBlock.className = "user-accordion";

    const contentId = `user-group-content-${index}`;

    userBlock.innerHTML = `
      <button type="button" class="user-accordion-toggle" data-target="${contentId}">
        <div class="user-accordion-left">
          <div class="user-accordion-title">${userGroup.userName}</div>
          <div class="user-accordion-subtitle">${userGroup.userEmail}</div>
        </div>

        <div class="user-accordion-right">
          <span class="user-accordion-badge">${userGroup.reportsCount} denúncia(s)</span>
          <span class="user-accordion-icon">▼</span>
        </div>
      </button>

      <div class="user-accordion-content" id="${contentId}">
        <div class="ads-group-wrapper"></div>
      </div>
    `;

    const adsWrapper = userBlock.querySelector(".ads-group-wrapper");

    Object.values(userGroup.ads).forEach(adGroup => {
      const adBlock = document.createElement("div");
      adBlock.className = "ad-group-card";

      const reportsHtml = adGroup.reports.map(item => {
        return `
          <div class="report-item">
            <div class="report-item-body">
              <div class="report-row">
                <span>Motivo:</span>
                <strong>${item.reporter_message}</strong>
              </div>

              <div class="report-row">
                <span>Status:</span>
                <strong>${item.status}</strong>
              </div>

              <div class="report-row">
                <span>Criada em:</span>
                <strong>${item.created_at ? new Date(item.created_at).toLocaleString("pt-BR") : "-"}</strong>
              </div>

              <div class="report-row">
                <span>Anúncio bloqueado:</span>
                <strong>${item.blocked_until ? new Date(item.blocked_until).toLocaleString("pt-BR") : "Não bloqueado"}</strong>
              </div>

              <div class="report-row">
                <span>Conta bloqueada:</span>
                <strong>${item.user_blocked_until ? new Date(item.user_blocked_until).toLocaleString("pt-BR") : "Não bloqueada"}</strong>
              </div>
            </div>

            <div class="actions">
              <input type="number" min="1" id="days-${item.id}" placeholder="Dias">

              <a
                href="/ads/${item.ad_id}/page"
                target="_blank"
                rel="noopener noreferrer"
                class="view-ad-btn"
              >
                Ver anúncio
              </a>

              <button type="button" class="resolve-btn" onclick="resolveReport(${item.id})">
                Concluir denúncia
              </button>

              <button type="button" class="block-btn" onclick="blockUser(${item.reported_user_id}, ${item.id})">
                Bloquear conta
              </button>

              ${
                item.user_blocked_until
                  ? `<button type="button" class="unblock-user-btn" onclick="unblockUser(${item.reported_user_id})">
                      Desbloquear conta
                    </button>`
                  : ""
              }

              <button type="button" class="block-ad-btn" onclick="blockAd(${item.ad_id}, ${item.id})">
                Bloquear anúncio
              </button>

              ${
                item.blocked_until
                  ? `<button type="button" class="unblock-btn" onclick="unblockAd(${item.ad_id})">
                      Desbloquear anúncio
                    </button>`
                  : ""
              }
            </div>
          </div>
        `;
      }).join("");

      adBlock.innerHTML = `
        <div class="ad-group-header">
          <div class="ad-group-title">${adGroup.adTitle}</div>
          <div class="ad-group-badge">${adGroup.reports.length} denúncia(s)</div>
        </div>

        <div class="reports-items-list">
          ${reportsHtml}
        </div>
      `;

      adsWrapper.appendChild(adBlock);
    });

    reportsList.appendChild(userBlock);
  });

  bindUserAccordion();
}

function bindUserAccordion() {
  const toggles = document.querySelectorAll(".user-accordion-toggle");

  toggles.forEach(toggle => {
    toggle.addEventListener("click", () => {
      const targetId = toggle.getAttribute("data-target");
      const content = document.getElementById(targetId);

      if (!content) return;

      const isOpen = content.classList.contains("open");

      content.classList.toggle("open", !isOpen);
      toggle.classList.toggle("open", !isOpen);
    });
  });
}

async function loadReports() {
  if (!ensureAdmin()) return;

  try {
    const response = await fetch(`/admin/reports?user_id=${savedUser.id}&status=OPEN`);
    const data = await response.json();

    if (!response.ok) {
      reportsList.innerHTML = `<div class="muted">${data.message || "Erro ao carregar denúncias."}</div>`;
      return;
    }

    renderReports(data);
  } catch (error) {
    console.error("Erro ao carregar denúncias:", error);
    reportsList.innerHTML = `<div class="muted">Erro ao carregar denúncias.</div>`;
  }
}

async function blockUser(targetUserId, reportId) {
  const daysInput = document.getElementById(`days-${reportId}`);
  const days = daysInput ? daysInput.value.trim() : "";

  if (!days) {
    alert("Informe a quantidade de dias.");
    return;
  }

  try {
    const response = await fetch(`/admin/users/${targetUserId}/block`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        admin_user_id: savedUser.id,
        days: Number(days),
        report_id: reportId
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao bloquear usuário.");
      return;
    }

    alert(data.message || "Usuário bloqueado com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao bloquear usuário:", error);
    alert("Erro ao bloquear usuário.");
  }
}

async function blockAd(adId, reportId) {
  const daysInput = document.getElementById(`days-${reportId}`);
  const days = daysInput ? daysInput.value.trim() : "";

  if (!days) {
    alert("Informe a quantidade de dias.");
    return;
  }

  try {
    const response = await fetch(`/admin/ads/${adId}/block`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
	  body: JSON.stringify({
        admin_user_id: savedUser.id,
        days: Number(days),
        report_id: reportId
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao bloquear anúncio.");
      return;
    }

    alert(data.message || "Anúncio bloqueado com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao bloquear anúncio:", error);
    alert("Erro ao bloquear anúncio.");
  }
}

async function unblockUser(targetUserId) {
  const confirmed = confirm("Deseja desbloquear este usuário?");
  if (!confirmed) return;

  try {
    const response = await fetch(`/admin/users/${targetUserId}/unblock`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        admin_user_id: savedUser.id
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao desbloquear usuário.");
      return;
    }

    alert(data.message || "Usuário desbloqueado com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao desbloquear usuário:", error);
    alert("Erro ao desbloquear usuário.");
  }
}

async function unblockAd(adId) {
  const confirmed = confirm("Deseja desbloquear este anúncio?");
  if (!confirmed) return;

  try {
    const response = await fetch(`/admin/ads/${adId}/unblock`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        admin_user_id: savedUser.id
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao desbloquear anúncio.");
      return;
    }

    alert(data.message || "Anúncio desbloqueado com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao desbloquear anúncio:", error);
    alert("Erro ao desbloquear anúncio.");
  }
}

async function resolveReport(reportId) {
  const confirmed = confirm("Deseja concluir esta denúncia?");
  if (!confirmed) return;

  try {
    const response = await fetch(`/admin/reports/${reportId}/resolve`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        admin_user_id: savedUser.id
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao concluir denúncia.");
      return;
    }

    alert(data.message || "Denúncia concluída com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao concluir denúncia:", error);
    alert("Erro ao concluir denúncia.");
  }
}

loadReports();