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

	function getActionLabel(action, days) {
	  switch (action) {
		case "ONLY_RESOLVED":
		  return "Somente concluída";
		case "USER_BLOCKED":
		  return days ? `Usuário bloqueado por ${days} dia(s)` : "Usuário bloqueado";
		case "AD_BLOCKED":
		  return days ? `Anúncio bloqueado por ${days} dia(s)` : "Anúncio bloqueado";
		default:
		  return "Não informado";
	  }
	}

  if (!items.length) {
    reportsList.innerHTML = `<div class="muted">Nenhuma denúncia concluída encontrada.</div>`;
    return;
  }

  items.forEach(item => {
    const div = document.createElement("div");
    div.className = "report-card";
    div.innerHTML = `
      <div class="report-header">
        <div class="report-title">${item.ad_title || "Anúncio sem título"}</div>
        <div class="report-status">${item.status}</div>
      </div>

      <div class="report-body">
        <div class="report-row">
          <span>Usuário:</span>
          <strong>${item.reported_user_name || "Não informado"}</strong>
        </div>

        <div class="report-row">
          <span>Email:</span>
          <strong>${item.reported_user_email || "Não informado"}</strong>
        </div>

        <div class="report-row">
          <span>Motivo:</span>
          <strong>${item.reporter_message}</strong>
        </div>

        <div class="report-row">
          <span>Total denúncias:</span>
          <strong>${item.total_reports || 0}</strong>
        </div>

        <div class="report-row">
          <span>Ação tomada:</span>
          <strong>${getActionLabel(item.action_taken, item.action_days)}</strong>
        </div>
		
		${
		  item.action_taken === "AD_BLOCKED"
			? `
			  <div class="report-row">
				<span>Anúncio bloqueado até:</span>
				<strong>${item.blocked_until ? new Date(item.blocked_until).toLocaleString("pt-BR") : "Não informado"}</strong>
			  </div>
			`
			: ""
		}

		${
		  item.action_taken === "USER_BLOCKED"
			? `
			  <div class="report-row">
				<span>Usuário bloqueado até:</span>
				<strong>${item.user_blocked_until ? new Date(item.user_blocked_until).toLocaleString("pt-BR") : "Não informado"}</strong>
			  </div>
			`
			: ""
		}

        <div class="report-row">
          <span>Concluída em:</span>
          <strong>${item.reviewed_at ? new Date(item.reviewed_at).toLocaleString("pt-BR") : "-"}</strong>
        </div>

        <div class="report-row">
          <span>Concluída por:</span>
          <strong>${item.reviewed_by_admin_name || "-"}</strong>
        </div>
      </div>

      <div class="report-footer">
        Criada em: ${item.created_at ? new Date(item.created_at).toLocaleString("pt-BR") : "-"}
      </div>

		<div class="actions">
		  <a
			href="/ads/${item.ad_id}/page"
			target="_blank"
			rel="noopener noreferrer"
			class="view-ad-btn"
		  >
			Ver anúncio
		  </a>

		  ${
			item.action_taken === "AD_BLOCKED"
			  ? `
				<input type="number" min="1" id="history-days-${item.id}" placeholder="Dias">
				<button type="button" class="edit-block-btn" onclick="updateAdBlockFromHistory(${item.ad_id}, ${item.id})">
				  Alterar bloqueio
				</button>
			  `
			  : ""
		  }

		  ${
			item.action_taken === "AD_BLOCKED" && item.blocked_until
			  ? `<button type="button" class="unblock-btn" onclick="unblockAdFromHistory(${item.ad_id})">
				  Desbloquear anúncio
				</button>`
			  : ""
		  }

		  ${
			item.action_taken === "USER_BLOCKED" && item.user_blocked_until
			  ? `<button type="button" class="unblock-user-btn" onclick="unblockUserFromHistory(${item.reported_user_id})">
				  Desbloquear usuário
				</button>`
			  : ""
		  }

		  <button type="button" class="delete-ad-btn" onclick="deleteAdFromHistory(${item.ad_id})">
			Excluir anúncio
		  </button>
		</div>
    `;
    reportsList.appendChild(div);
  });
}

async function loadReports() {
  if (!ensureAdmin()) return;

  try {
    const response = await fetch(`/admin/reports?user_id=${savedUser.id}&status=RESOLVED`);
    const data = await response.json();

    if (!response.ok) {
      reportsList.innerHTML = `<div class="muted">${data.message || "Erro ao carregar histórico de denúncias."}</div>`;
      return;
    }

    renderReports(data);
  } catch (error) {
    console.error("Erro ao carregar histórico de denúncias:", error);
    reportsList.innerHTML = `<div class="muted">Erro ao carregar histórico de denúncias.</div>`;
  }
}

async function unblockAdFromHistory(adId) {
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

async function unblockUserFromHistory(userId) {
  const confirmed = confirm("Deseja desbloquear este usuário?");
  if (!confirmed) return;

  try {
    const response = await fetch(`/admin/users/${userId}/unblock`, {
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

async function deleteAdFromHistory(adId) {
  const confirmed = confirm("Deseja realmente excluir este anúncio?");
  if (!confirmed) return;

  try {
    const response = await fetch(`/admin/ads/${adId}/delete`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        admin_user_id: savedUser.id
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao excluir anúncio.");
      return;
    }

    alert(data.message || "Anúncio excluído com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao excluir anúncio:", error);
    alert("Erro ao excluir anúncio.");
  }
}

async function updateAdBlockFromHistory(adId, reportId) {
  const input = document.getElementById(`history-days-${reportId}`);
  const days = input ? Number(input.value) : 0;

  if (!days || days <= 0) {
    alert("Informe uma quantidade de dias maior que zero.");
    return;
  }

  const confirmed = confirm(`Deseja alterar o bloqueio deste anúncio para ${days} dia(s)?`);
  if (!confirmed) return;

  try {
    const response = await fetch(`/admin/ads/${adId}/block`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        admin_user_id: savedUser.id,
        days: days
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao alterar bloqueio do anúncio.");
      return;
    }

    alert(data.message || "Bloqueio do anúncio alterado com sucesso.");
    loadReports();
  } catch (error) {
    console.error("Erro ao alterar bloqueio do anúncio:", error);
    alert("Erro ao alterar bloqueio do anúncio.");
  }
}

loadReports();