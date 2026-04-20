function getSavedUser() {
  try {
    return JSON.parse(localStorage.getItem("catalogo_user") || "null");
  } catch (error) {
    console.error("Erro ao ler catalogo_user do localStorage:", error);
    localStorage.removeItem("catalogo_user");
    return null;
  }
}

function setSavedUser(user) {
  if (user) {
    localStorage.setItem("catalogo_user", JSON.stringify(user));
    return;
  }

  localStorage.removeItem("catalogo_user");
}

async function syncUserWithServerSession() {
  try {
    const response = await fetch("/auth/session", {
      method: "GET",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json"
      }
    });

    if (!response.ok) {
      console.error("Não foi possível validar a sessão atual.");
      setSavedUser(null);
      return null;
    }

    const data = await response.json();

    if (data && data.authenticated && data.user) {
      setSavedUser(data.user);
      return data.user;
    }

    setSavedUser(null);
    return null;
  } catch (error) {
    console.error("Erro ao sincronizar sessão com o servidor:", error);
    setSavedUser(null);
    return null;
  }
}

function isAdminUser(user) {
  if (!user) return false;
  return user.is_admin === true || user.role === "admin";
}

function ensureAdminOverlay() {
  let overlay = document.querySelector(".admin-sidebar-overlay");

  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "admin-sidebar-overlay";
    document.body.appendChild(overlay);
  }

  return overlay;
}

function ensureAdminFloatingToggle() {
  let button = document.querySelector(".admin-floating-toggle");

  if (!button) {
    button = document.createElement("button");
    button.type = "button";
    button.className = "admin-floating-toggle";
    button.setAttribute("aria-label", "Abrir menu do administrador");
    button.innerHTML = "☰";
    document.body.appendChild(button);
  }

  return button;
}

function closeAdminSidebar() {
  const adminSidebar = document.getElementById("adminSidebar");
  const overlay = document.querySelector(".admin-sidebar-overlay");

  if (adminSidebar) {
    adminSidebar.classList.remove("open");

    if (window.innerWidth <= 900) {
      adminSidebar.style.display = "none";
    }
  }

  if (overlay) {
    overlay.classList.remove("open");
  }
}

function openAdminSidebar() {
  const adminSidebar = document.getElementById("adminSidebar");
  const overlay = ensureAdminOverlay();

  if (adminSidebar) {
    adminSidebar.style.display = "flex";
    adminSidebar.classList.add("open");
  }

  overlay.classList.add("open");
}

function bindAdminSidebarMobile() {
  const adminSidebar = document.getElementById("adminSidebar");
  const overlay = ensureAdminOverlay();
  const floatingButton = ensureAdminFloatingToggle();

  if (!adminSidebar || !floatingButton) return;

  floatingButton.addEventListener("click", () => {
    const isOpen = adminSidebar.classList.contains("open");

    if (isOpen) {
      closeAdminSidebar();
    } else {
      openAdminSidebar();
    }
  });

  overlay.addEventListener("click", () => {
    closeAdminSidebar();
  });

	window.addEventListener("resize", () => {
	  closeAdminSidebar();
	  applyAdminSidebarLayout();
	});
}

function applyAdminSidebarLayout() {
  const savedUser = getSavedUser();
  const adminSidebar = document.getElementById("adminSidebar");
  const floatingButton = ensureAdminFloatingToggle();

  if (!isAdminUser(savedUser) || !adminSidebar) {
    document.body.classList.remove("admin-has-sidebar");

    if (adminSidebar) {
      adminSidebar.style.display = "none";
      adminSidebar.classList.remove("open");
    }

    if (floatingButton) {
      floatingButton.style.display = "none";
    }

    return;
  }

  document.body.classList.add("admin-has-sidebar");

  if (window.innerWidth > 900) {
    adminSidebar.style.display = "flex";
    adminSidebar.classList.remove("open");

    if (floatingButton) {
      floatingButton.style.display = "none";
    }

    const overlay = document.querySelector(".admin-sidebar-overlay");
    if (overlay) {
      overlay.classList.remove("open");
    }
  } else {
    adminSidebar.style.display = "none";

    if (floatingButton) {
      floatingButton.style.display = "flex";
    }
  }
}

async function logout() {
  try {
    await fetch("/logout", {
      method: "POST",
      credentials: "same-origin"
    });
  } catch (error) {
    console.error("Erro ao fazer logout:", error);
  }

  setSavedUser(null);
  window.location.href = "/auth-page";
}

function getPlanLabel(plan) {
  const labels = {
    FREE: "FREE",
    VIP_BRONZE: "VIP Bronze",
    VIP_PRATA: "VIP Prata",
    VIP_OURO: "VIP Ouro",
    VIP_PREMIUM: "VIP Premium"
  };
  return labels[plan] || plan || "FREE";
}

function getTopbarPlanText(user) {
  if (!user) return "";

  let planText = user.plan_label || getPlanLabel(user.plan);

  if (user.vip_expires_at) {
    const now = new Date();
    const expiresAt = new Date(user.vip_expires_at);
    const diffMs = expiresAt - now;
    const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays > 0) {
      planText = `${user.plan_label || getPlanLabel(user.plan)} (expira em ${diffDays} dias)`;
    } else {
      planText = `${user.plan_label || getPlanLabel(user.plan)} expirado`;
    }
  }

  return planText;
}

function getTopbarRemainingDaysText(user) {
  if (!user || !user.vip_expires_at) return "";

  const now = new Date();
  const expiresAt = new Date(user.vip_expires_at);
  const diffMs = expiresAt - now;
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays > 0) {
    return `${diffDays} dias`;
  }

  return "Expirado";
}

async function getSupportWhatsapp() {
  try {
    const response = await fetch("/public/support-whatsapp", {
      method: "GET",
      headers: {
        "Accept": "application/json"
      }
    });

    if (!response.ok) {
      return "";
    }

    const data = await response.json();
    return (data.support_whatsapp || "").trim();
  } catch (error) {
    console.error("Erro ao carregar WhatsApp de suporte:", error);
    return "";
  }
}

function buildWhatsappLink(rawNumber) {
  const digits = String(rawNumber || "").replace(/\D/g, "");

  if (!digits) return "";

  const message = "Olá, preciso de suporte para o CataLogin";
  const encodedMessage = encodeURIComponent(message);

  return `https://wa.me/${digits}?text=${encodedMessage}`;
}

async function renderSharedTopbar() {
  const topMenu = document.getElementById("topActionsMenu");
  const bottomMenu = document.getElementById("mobileBottomNav");
  const userInfo = document.getElementById("topbarUserInfo");
  const savedUser = getSavedUser();

  if (!topMenu || !bottomMenu || !userInfo) return;

  const supportWhatsapp = await getSupportWhatsapp();
  const whatsappLink = buildWhatsappLink(supportWhatsapp);
  
  const whatsappIcon = whatsappLink
    ? `
      <a
        href="${whatsappLink}"
        class="topbar-whatsapp-link"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Falar com o suporte no WhatsApp"
        title="Falar com o suporte no WhatsApp"
      >
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M19.11 17.2c-.27-.14-1.58-.78-1.83-.87-.24-.09-.42-.14-.6.14-.18.27-.69.87-.85 1.05-.16.18-.31.2-.58.07-.27-.14-1.14-.42-2.17-1.34-.8-.71-1.34-1.58-1.49-1.85-.16-.27-.02-.41.12-.54.12-.12.27-.31.4-.47.13-.16.18-.27.27-.45.09-.18.04-.34-.02-.47-.07-.14-.6-1.45-.82-1.98-.22-.53-.45-.46-.6-.47h-.51c-.18 0-.47.07-.71.34-.24.27-.93.91-.93 2.22 0 1.31.96 2.58 1.09 2.76.13.18 1.88 2.87 4.56 4.02.64.27 1.14.43 1.53.55.64.2 1.22.17 1.68.1.51-.08 1.58-.64 1.8-1.25.22-.61.22-1.13.16-1.25-.07-.11-.24-.18-.51-.31z"></path>
          <path d="M16.03 3C8.85 3 3.03 8.82 3.03 16c0 2.53.72 4.99 2.08 7.1L3 29l6.07-1.99A12.92 12.92 0 0 0 16.03 29C23.2 29 29.03 23.18 29.03 16S23.2 3 16.03 3zm0 23.67c-2.16 0-4.28-.58-6.14-1.69l-.44-.26-3.6 1.18 1.17-3.51-.29-.46a10.61 10.61 0 0 1-1.64-5.63c0-5.9 4.8-10.7 10.7-10.7 2.86 0 5.54 1.11 7.56 3.13a10.6 10.6 0 0 1 3.14 7.56c0 5.9-4.8 10.69-10.7 10.69z"></path>
        </svg>
      </a>
    `
    : "";

  let userBlock = "";
  let guestMessage = "";
  let adminButton = "";
  let authButton = "";

  if (savedUser) {
    const planLabel = savedUser.plan_label || getPlanLabel(savedUser.plan);
    const remainingDaysText = getTopbarRemainingDaysText(savedUser);

	userBlock = `
      <div class="topbar-user-summary">
        ${whatsappIcon}
        <div class="topbar-user-lines">
          <span class="topbar-user-name">${savedUser.name || "Usuário"}</span>
          <span class="topbar-plan-line">Plano: ${planLabel}</span>
          ${remainingDaysText ? `<span class="topbar-plan-line">${remainingDaysText}</span>` : ""}
        </div>
      </div>
    `;

    authButton = `<button type="button" onclick="logout()">Sair</button>`;
  } else {
	guestMessage = `
      <div class="topbar-user-summary">
        ${whatsappIcon}
        <div class="topbar-user-lines">
          <span>Olá, visitante</span>
          <span class="topbar-plan-line">
            Faça login para acessar<br>todos os recursos do app
          </span>
        </div>
      </div>
    `;
    authButton = `<button type="button" onclick="window.location.href='/auth-page'">Entrar</button>`;
  }

  if (isAdminUser(savedUser)) {
    adminButton = `<button type="button" onclick="window.location.href='/admin/dashboard-page'">Admin</button>`;
  }

  userInfo.innerHTML = savedUser ? userBlock : guestMessage;

  topMenu.innerHTML = `
    ${adminButton}
    <button type="button" onclick="window.location.href='/search-page'">Pesquisa</button>
    <button type="button" onclick="window.location.href='/vitrine-page'">Vitrine</button>
    <button type="button" onclick="window.location.href='/feed-page'">Feed</button>
    <button type="button" onclick="window.location.href='${savedUser ? "/create-ad-page" : "/auth-page"}'">Anunciar</button>
    ${savedUser ? `<button type="button" onclick="window.location.href='/profile-page'">Perfil</button>` : ""}
    <button type="button" class="vip-btn" onclick="window.location.href='/vip-page'">Tornar-se VIP</button>
    ${authButton}
  `;

  bottomMenu.innerHTML = `
    <button type="button" onclick="window.location.href='/search-page'">Pesquisa</button>
    <button type="button" onclick="window.location.href='/vitrine-page'">Vitrine</button>
    <button type="button" onclick="window.location.href='/feed-page'">Feed</button>
    <button type="button" onclick="window.location.href='${savedUser ? "/create-ad-page" : "/auth-page"}'">Anunciar</button>
    ${savedUser ? `<button type="button" onclick="window.location.href='/profile-page'">Perfil</button>` : ""}
    <button type="button" class="vip-btn" onclick="window.location.href='/vip-page'">VIP</button>
    ${
      savedUser
        ? `<button type="button" onclick="logout()">Sair</button>`
        : `<button type="button" onclick="window.location.href='/auth-page'">Entrar</button>`
    }
  `;
}

async function requireLogin() {
  const user = await syncUserWithServerSession();

  if (user && user.id) {
    return true;
  }

  localStorage.setItem("redirect_after_login", window.location.pathname);
  window.location.href = "/auth-page";
  return false;
}

document.addEventListener("DOMContentLoaded", async function () {
  await syncUserWithServerSession();
  renderSharedTopbar();
  applyAdminSidebarLayout();
  bindAdminSidebarMobile();
});

(function forceCleanServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  const cleaned = sessionStorage.getItem("sw_cleaned_global");

  navigator.serviceWorker.getRegistrations().then(async (registrations) => {
    if (registrations.length === 0) return;

    console.log("Limpando service workers antigos...");

    await Promise.all(registrations.map(r => r.unregister()));

    if (window.caches) {
      const keys = await caches.keys();
      await Promise.all(keys.map(k => caches.delete(k)));
    }

    if (!cleaned) {
      sessionStorage.setItem("sw_cleaned_global", "1");
      window.location.reload();
    }
  });
})();