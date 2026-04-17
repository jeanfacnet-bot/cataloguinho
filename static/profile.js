const profileForm = document.getElementById("profileForm");
const profileName = document.getElementById("profileName");
const profileEmail = document.getElementById("profileEmail");
const currentPassword = document.getElementById("currentPassword");
const newPassword = document.getElementById("newPassword");
const confirmPassword = document.getElementById("confirmPassword");
const profileMessage = document.getElementById("profileMessage");
const vipHistoryContainer = document.getElementById("vipHistoryContainer");

let savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

function showProfileMessage(message, type) {
  profileMessage.textContent = message;
  profileMessage.className = `profile-message ${type}`;
}

function clearProfileMessage() {
  profileMessage.textContent = "";
  profileMessage.className = "profile-message";
}

function formatDate(value) {
  if (!value) return "-";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "-";

  return date.toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short"
  });
}

function formatMoney(value) {
  const number = Number(value || 0);

  return number.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL"
  });
}

function getStatusLabel(status) {
  const map = {
    approved: "Aprovado",
    pending: "Pendente",
    cancelled: "Cancelado",
    rejected: "Recusado"
  };

  return map[status] || status || "-";
}

function renderVipHistory(items) {
  if (!vipHistoryContainer) return;

  if (!Array.isArray(items) || !items.length) {
    vipHistoryContainer.innerHTML = `
      <div class="vip-history-empty">
        Você ainda não possui compras de plano registradas.
      </div>
    `;
    return;
  }

  vipHistoryContainer.innerHTML = items.map(item => `
    <div class="vip-history-card">
      <div class="vip-history-top">
        <div class="vip-history-plan">${item.plan_label || item.plan || "-"}</div>
        <div class="vip-history-status ${(item.payment_status || "").toLowerCase()}">
          ${getStatusLabel((item.payment_status || "").toLowerCase())}
        </div>
      </div>

      <div class="vip-history-meta">
        <div><strong>Valor:</strong> ${formatMoney(item.amount)}</div>
        <div><strong>Forma de pagamento:</strong> ${item.payment_method || "pix"}</div>
        <div><strong>ID do pagamento:</strong> ${item.payment_id || "-"}</div>
        <div><strong>Criado em:</strong> ${formatDate(item.created_at || item.mp_created_at)}</div>
        <div><strong>Aprovado em:</strong> ${formatDate(item.approved_at)}</div>
        <div><strong>Expira em:</strong> ${formatDate(item.expires_at)}</div>
      </div>
    </div>
  `).join("");
}

async function loadVipHistory() {
  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser || !savedUser.id) {
    window.location.href = "/auth-page";
    return;
  }

  if (vipHistoryContainer) {
    vipHistoryContainer.innerHTML = `
      <div class="vip-history-empty">Carregando histórico...</div>
    `;
  }

  try {
    const response = await fetch(`/users/${savedUser.id}/vip-purchases`);
    const data = await response.json();

    if (!response.ok) {
      if (vipHistoryContainer) {
        vipHistoryContainer.innerHTML = `
          <div class="vip-history-empty">
            ${data.message || "Erro ao carregar histórico de pagamentos."}
          </div>
        `;
      }
      return;
    }

    renderVipHistory(data);
  } catch (error) {
    console.error("Erro ao carregar histórico VIP:", error);

    if (vipHistoryContainer) {
      vipHistoryContainer.innerHTML = `
        <div class="vip-history-empty">
          Erro ao carregar histórico de pagamentos.
        </div>
      `;
    }
  }
}

async function loadProfile() {
  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser || !savedUser.id) {
    window.location.href = "/auth-page";
    return;
  }

  try {
    const response = await fetch(`/users/${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) {
      showProfileMessage(data.message || "Erro ao carregar perfil.", "error");
      return;
    }

    profileName.value = data.name || "";
    profileEmail.value = data.email || "";
  } catch (error) {
    console.error("Erro ao carregar perfil:", error);
    showProfileMessage("Erro ao carregar perfil.", "error");
  }
}

profileForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearProfileMessage();

  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser || !savedUser.id) {
    window.location.href = "/auth-page";
    return;
  }

  const payload = {
    name: profileName.value.trim(),
    email: profileEmail.value.trim(),
    current_password: currentPassword.value.trim(),
    new_password: newPassword.value.trim(),
    confirm_password: confirmPassword.value.trim()
  };

  try {
    const response = await fetch(`/users/${savedUser.id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      showProfileMessage(data.message || "Erro ao atualizar perfil.", "error");
      return;
    }

    if (data.user) {
      localStorage.setItem("catalogo_user", JSON.stringify(data.user));
    }

    currentPassword.value = "";
    newPassword.value = "";
    confirmPassword.value = "";

    showProfileMessage(data.message || "Perfil atualizado com sucesso.", "success");
  } catch (error) {
    console.error("Erro ao atualizar perfil:", error);
    showProfileMessage("Erro ao atualizar perfil.", "error");
  }
});

loadProfile();
loadVipHistory();