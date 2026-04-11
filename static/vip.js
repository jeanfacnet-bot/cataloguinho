let savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

const userStatus = document.getElementById("userStatus");
const vipMessage = document.getElementById("vipMessage");
const upgradeButtons = document.querySelectorAll(".upgrade-plan-btn");
const freePlanFeatures = document.getElementById("freePlanFeatures");
const bronzePlanFeatures = document.getElementById("bronzePlanFeatures");
const prataPlanFeatures = document.getElementById("prataPlanFeatures");
const ouroPlanFeatures = document.getElementById("ouroPlanFeatures");
const premiumPlanFeatures = document.getElementById("premiumPlanFeatures");

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

function buildPlanFeatures(planName, rules) {
  const features = [];

  features.push(`Cadastro de ${rules.ads_limit} anúncio${rules.ads_limit === 1 ? "" : "s"}`);
  features.push(`Até ${rules.keywords_limit} palavra${rules.keywords_limit === 1 ? "" : "s"}-chave`);

  if (rules.can_use_images) {
    features.push("Pode usar imagem");
  } else {
    features.push("Sem imagem");
  }

  if (rules.can_use_videos) {
    features.push("Pode usar vídeo");
  } else {
    features.push("Sem vídeo");
  }

  if (rules.can_appear_in_vip_list) {
    features.push("Aparece na tela inicial de pesquisa");
  }

  if (rules.can_show_full_details) {
    features.push("Mostra detalhes completos");
  }
  
  if (rules.can_use_vitrine) {
    features.push("Aparece na vitrine");
  } 

  return features.map(item => `<li>${item}</li>`).join("");
}

async function loadPlansConfig() {
  try {
    const response = await fetch("/plans-config");
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || "Erro ao carregar os planos");
    }

    if (freePlanFeatures) {
      freePlanFeatures.innerHTML = buildPlanFeatures("FREE", data.free);
    }

    if (bronzePlanFeatures) {
      bronzePlanFeatures.innerHTML = buildPlanFeatures("VIP_BRONZE", data.bronze);
    }

    if (prataPlanFeatures) {
      prataPlanFeatures.innerHTML = buildPlanFeatures("VIP_PRATA", data.prata);
    }

    if (ouroPlanFeatures) {
      ouroPlanFeatures.innerHTML = buildPlanFeatures("VIP_OURO", data.ouro);
    }

    if (premiumPlanFeatures) {
      premiumPlanFeatures.innerHTML = buildPlanFeatures("VIP_PREMIUM", data.premium);
    }
  } catch (error) {
    console.error("Erro ao carregar configuração dos planos:", error);
  }
}

async function refreshCurrentUser() {
  if (!savedUser || !savedUser.id) return;

  try {
    const response = await fetch(`/users/${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) return;

    savedUser = data;
    localStorage.setItem("catalogo_user", JSON.stringify(data));
  } catch (error) {
    console.error("Erro ao atualizar usuário atual:", error);
  }
}

function showMessage(message, type) {
  if (!vipMessage) return;
  vipMessage.textContent = message;
  vipMessage.className = `message-box ${type}`;
}

function getVipStatusText(user) {
  if (!user) return "";

  const currentPlanLabel = user.plan_label || getPlanLabel(user.plan);

  if (user.plan === "FREE") {
    return "Plano atual: FREE";
  }

  if (!user.vip_expires_at) {
    return `Plano atual: ${currentPlanLabel}`;
  }

  const expiresAt = new Date(user.vip_expires_at);
  const now = new Date();
  const diffMs = expiresAt.getTime() - now.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays <= 0) {
    return `${currentPlanLabel} expirado`;
  }

  if (diffDays === 1) {
    return `${currentPlanLabel} expira em 1 dia`;
  }

  return `${currentPlanLabel} expira em ${diffDays} dias`;
}

function updateButtonsState() {
  upgradeButtons.forEach((button) => {
    const targetPlan = button.dataset.plan;

    if (!savedUser) {
      const originalTextMap = {
        VIP_BRONZE: "Escolher Bronze",
        VIP_PRATA: "Escolher Prata",
        VIP_OURO: "Escolher Ouro",
        VIP_PREMIUM: "Escolher Premium"
      };

      button.disabled = false;
      button.textContent = originalTextMap[targetPlan] || "Escolher plano";
      button.style.opacity = "1";
      button.style.cursor = "pointer";
      return;
    }

    if (savedUser.plan === targetPlan && savedUser.vip_expires_at) {
      const expiresAt = new Date(savedUser.vip_expires_at);
      const now = new Date();

      if (expiresAt > now) {
        button.disabled = true;
        button.textContent = `Plano atual: ${getPlanLabel(targetPlan)}`;
        button.style.opacity = "0.6";
        button.style.cursor = "not-allowed";
        return;
      }
    }

    const originalTextMap = {
      VIP_BRONZE: "Escolher Bronze",
      VIP_PRATA: "Escolher Prata",
      VIP_OURO: "Escolher Ouro",
      VIP_PREMIUM: "Escolher Premium"
    };

    button.disabled = false;
    button.textContent = originalTextMap[targetPlan] || "Escolher plano";
    button.style.opacity = "1";
    button.style.cursor = "pointer";
  });
}

function renderUserStatus() {
  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser) {
    if (userStatus) {
      userStatus.innerHTML = "Você não está logado. Faça login para escolher um plano.";
    }
    updateButtonsState();
    return;
  }

  const vipStatusText = getVipStatusText(savedUser);

  if (userStatus) {
    userStatus.innerHTML = `
      Usuário: <strong>${savedUser.name}</strong><br>
      <strong>${vipStatusText}</strong>
    `;
  }

  updateButtonsState();
}

async function upgradePlan(targetPlan) {
  if (!savedUser) {
    showMessage("Faça login antes de tentar o upgrade.", "error");
    return;
  }

  try {
    upgradeButtons.forEach((btn) => {
      btn.disabled = true;
      btn.style.opacity = "0.6";
      btn.style.cursor = "not-allowed";
    });

    const response = await fetch(`/upgrade-vip/${savedUser.id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        plan: targetPlan
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showMessage(data.message || "Erro ao fazer upgrade.", "error");
      renderUserStatus();
      return;
    }

    localStorage.setItem("catalogo_user", JSON.stringify(data.user));
    savedUser = data.user;

    showMessage(data.message || "Upgrade realizado com sucesso.", "success");
	renderSharedTopbar();
    renderUserStatus();
  } catch (error) {
    showMessage("Erro ao conectar com o servidor.", "error");
    renderUserStatus();
  }
}

async function createVipPix(targetPlan) {
  if (!requireLogin()) return;

  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  try {
    upgradeButtons.forEach((btn) => {
      btn.disabled = true;
      btn.style.opacity = "0.6";
      btn.style.cursor = "not-allowed";
    });

    const response = await fetch("/vip/create-pix", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ plan: targetPlan })
    });

    const data = await response.json();

    if (!response.ok) {
      showMessage(data.message || "Erro ao gerar o pagamento.", "error");
      renderUserStatus();
      return;
    }

    localStorage.setItem("vip_checkout", JSON.stringify(data));
    window.location.href = "/vip-payment-page";
  } catch (error) {
    showMessage("Erro ao conectar com o servidor.", "error");
    renderUserStatus();
  }
}

upgradeButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const targetPlan = button.dataset.plan;
    await createVipPix(targetPlan);
  });
});

(async function initVipPage() {
  if (savedUser && savedUser.id) {
    await refreshCurrentUser();
  }

  renderUserStatus();
  loadPlansConfig();
})();