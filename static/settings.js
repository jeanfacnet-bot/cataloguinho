const savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const settingsStatus = document.getElementById("settingsStatus");
const supportWhatsapp = document.getElementById("supportWhatsapp");
const newUserVipEnabled =
  document.getElementById("newUserVipEnabled");

const newUserVipPlan =
  document.getElementById("newUserVipPlan");

const newUserVipDays =
  document.getElementById("newUserVipDays");

const allUsersVipPlan =
  document.getElementById("allUsersVipPlan");

const allUsersVipDays =
  document.getElementById("allUsersVipDays");

const grantVipToAllBtn =
  document.getElementById("grantVipToAllBtn");

const promotionMessage =
  document.getElementById("promotionMessage");

function isAdmin(user) {
  return !!user && (user.is_admin === true || user.role === "admin");
}

function setStatus(message, isError = false) {
  settingsStatus.textContent = message;
  settingsStatus.style.color = isError ? "#dc3545" : "#198754";
}

function getValue(id) {
  return document.getElementById(id);
}

function fillPlan(prefix, data) {
  getValue(`${prefix}AdsLimit`).value = data.ads_limit ?? 0;
  getValue(`${prefix}KeywordsLimit`).value = data.keywords_limit ?? 0;

  const priceInput = document.getElementById(`${prefix}Price`);
  if (priceInput) {
    priceInput.value = data.price ?? 0;
  }

  getValue(`${prefix}CanUseImages`).checked = !!data.can_use_images;
  getValue(`${prefix}CanUseVideos`).checked = !!data.can_use_videos;
  getValue(`${prefix}CanAppearInVipList`).checked = !!data.can_appear_in_vip_list;
  getValue(`${prefix}CanShowFullDetails`).checked = !!data.can_show_full_details;
  getValue(`${prefix}CanUseVitrine`).checked = !!data.can_use_vitrine;
  getValue(`${prefix}CanUseLocation`).checked = !!data.can_use_location;
}

function collectPlan(prefix) {
  const priceInput = document.getElementById(`${prefix}Price`);

  return {
    ads_limit: parseInt(getValue(`${prefix}AdsLimit`).value, 10),
    keywords_limit: parseInt(getValue(`${prefix}KeywordsLimit`).value, 10),
    price: priceInput ? parseFloat(priceInput.value || "0") : 0,
    can_use_images: getValue(`${prefix}CanUseImages`).checked,
    can_use_videos: getValue(`${prefix}CanUseVideos`).checked,
    can_appear_in_vip_list: getValue(`${prefix}CanAppearInVipList`).checked,
    can_show_full_details: getValue(`${prefix}CanShowFullDetails`).checked,
    can_use_vitrine: getValue(`${prefix}CanUseVitrine`).checked,
	can_use_location: getValue(`${prefix}CanUseLocation`).checked
  };
}

async function loadSettings() {
  if (!isAdmin(savedUser)) {
    setStatus("Acesso negado.", true);
    saveSettingsBtn.disabled = true;
    return;
  }

  try {
    setStatus("Carregando...");

    const response = await fetch(`/admin/settings?user_id=${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || "Erro ao carregar ajustes");
    }

    fillPlan("free", data.free);
    fillPlan("bronze", data.bronze);
    fillPlan("prata", data.prata);
    fillPlan("ouro", data.ouro);
    fillPlan("premium", data.premium);
	
	if (supportWhatsapp) {
      supportWhatsapp.value = data.support_whatsapp || "";
    }
	
	const promotions = data.promotions || {};

    if (newUserVipEnabled) {
      newUserVipEnabled.checked = Boolean(
        promotions.new_user_vip_enabled
      );
    }

    if (newUserVipPlan) {
      newUserVipPlan.value =
        promotions.new_user_vip_plan ||
        "VIP_BRONZE";
    }

    if (newUserVipDays) {
      newUserVipDays.value =
        promotions.new_user_vip_days || 30;
    }

    setStatus("Ajustes carregados com sucesso.");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Erro ao carregar ajustes.", true);
  }
}

async function saveSettings() {
  if (!isAdmin(savedUser)) {
    setStatus("Acesso negado.", true);
    return;
  }

  try {
    saveSettingsBtn.disabled = true;
    setStatus("Salvando...");

	const payload = {
      admin_user_id: savedUser.id,

      support_whatsapp:
        supportWhatsapp
          ? supportWhatsapp.value.trim()
          : "",

      promotions: {
        new_user_vip_enabled:
          newUserVipEnabled
            ? newUserVipEnabled.checked
            : false,

        new_user_vip_plan:
          newUserVipPlan
            ? newUserVipPlan.value
            : "VIP_BRONZE",

        new_user_vip_days:
          newUserVipDays
            ? Number(newUserVipDays.value)
            : 30
      },

      free: collectPlan("free"),
      bronze: collectPlan("bronze"),
      prata: collectPlan("prata"),
      ouro: collectPlan("ouro"),
      premium: collectPlan("premium")
    };

    const response = await fetch(`/admin/settings`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || "Erro ao salvar ajustes");
    }

    setStatus(data.message || "Ajustes salvos com sucesso.");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Erro ao salvar ajustes.", true);
  } finally {
    saveSettingsBtn.disabled = false;
  }
}

async function grantVipToAllUsers() {
  if (!isAdmin(savedUser)) {
    setPromotionStatus(
      "Acesso negado.",
      true
    );
    return;
  }

  const plan = allUsersVipPlan
    ? allUsersVipPlan.value
    : "VIP_BRONZE";

  const days = allUsersVipDays
    ? Number(allUsersVipDays.value)
    : 30;

  if (
    !Number.isInteger(days) ||
    days < 1 ||
    days > 365
  ) {
    setPromotionStatus(
      "Informe uma duração entre 1 e 365 dias.",
      true
    );
    return;
  }

  const planLabels = {
    VIP_BRONZE: "VIP Bronze",
    VIP_PRATA: "VIP Prata",
    VIP_OURO: "VIP Ouro",
    VIP_PREMIUM: "VIP Premium"
  };

  const confirmed = window.confirm(
    `Deseja conceder ${planLabels[plan]} ` +
    `por ${days} dias a todos os usuários?`
  );

  if (!confirmed) {
    return;
  }

  try {
    grantVipToAllBtn.disabled = true;
    grantVipToAllBtn.textContent =
      "Aplicando promoção...";

    setPromotionStatus(
      "Aplicando promoção..."
    );

    const response = await fetch(
      "/admin/promotions/grant-vip-all",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          admin_user_id: savedUser.id,
          plan: plan,
          days: days
        })
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.message ||
        "Erro ao aplicar promoção"
      );
    }

    setPromotionStatus(
      data.message ||
      "Promoção aplicada com sucesso."
    );

    window.alert(
      data.message ||
      "Promoção aplicada com sucesso."
    );
  } catch (error) {
    console.error(
      "Erro ao aplicar promoção:",
      error
    );

    setPromotionStatus(
      error.message ||
      "Erro ao aplicar promoção.",
      true
    );
  } finally {
    grantVipToAllBtn.disabled = false;
    grantVipToAllBtn.textContent =
      "Conceder VIP a todos";
  }
}


function setPromotionStatus(
  message,
  isError = false
) {
  if (!promotionMessage) {
    return;
  }

  promotionMessage.textContent = message;

  promotionMessage.style.color =
    isError
      ? "#dc3545"
      : "#198754";
}

if (saveSettingsBtn) {
  saveSettingsBtn.addEventListener(
    "click",
    saveSettings
  );
}

if (grantVipToAllBtn) {
  grantVipToAllBtn.addEventListener(
    "click",
    grantVipToAllUsers
  );
}

loadSettings();