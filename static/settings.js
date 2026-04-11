const savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const settingsStatus = document.getElementById("settingsStatus");

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
    can_use_vitrine: getValue(`${prefix}CanUseVitrine`).checked
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

saveSettingsBtn.addEventListener("click", saveSettings);
loadSettings();