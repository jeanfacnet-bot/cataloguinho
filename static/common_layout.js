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

function renderSharedTopbar() {
  const topMenu = document.getElementById("topActionsMenu");
  const bottomMenu = document.getElementById("mobileBottomNav");
  const userInfo = document.getElementById("topbarUserInfo");
  const savedUser = getSavedUser();

  if (!topMenu || !bottomMenu || !userInfo) return;

  let userBlock = "";
  let guestMessage = "";
  let adminButton = "";
  let authButton = "";

  if (savedUser) {
	  const planLabel = savedUser.plan_label || getPlanLabel(savedUser.plan);
	  const remainingDaysText = getTopbarRemainingDaysText(savedUser);

	  userBlock = `
		<div class="topbar-user-lines">
		  <span class="topbar-user-name">${savedUser.name || "Usuário"}</span>
		  <span class="topbar-plan-line">Plano: ${planLabel}</span>
		  ${remainingDaysText ? `<span class="topbar-plan-line">${remainingDaysText}</span>` : ""}
		</div>
	  `;
	  authButton = `<button type="button" onclick="logout()">Sair</button>`;
	} else {
	  guestMessage = `
		<div class="topbar-user-lines">
		  <span>Olá, visitante</span>
			<span class="topbar-plan-line">
			  Faça login para acessar<br>todos os recursos do app
			</span>
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
	  ${savedUser
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