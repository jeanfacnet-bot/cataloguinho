const adForm = document.getElementById("adForm");
const adMessage = document.getElementById("adMessage");
const userInfo = document.getElementById("userInfo");
const myAds = document.getElementById("myAds");

const stateSelect = document.getElementById("state");
const citySelect = document.getElementById("city");
const neighborhoodSelect = document.getElementById("neighborhood");
const streetSelect = document.getElementById("street");
const complementInput = document.getElementById("complement");
const mainImageInput = document.getElementById("mainImage");
const mainVideoInput = document.getElementById("mainVideo");
const imageUploadBlock = document.getElementById("imageUploadBlock");
const videoUploadBlock = document.getElementById("videoUploadBlock");
const imageUpgradeMessage = document.getElementById("imageUpgradeMessage");
const videoUpgradeMessage = document.getElementById("videoUpgradeMessage");

let savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
let plansConfig = null;
let editingAdId = null;
const cancelEditBtn = document.getElementById("cancelEditBtn");

async function loadPlansConfig() {
  try {
    const response = await fetch("/plans-config");
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || "Erro ao carregar configuração dos planos.");
    }

    plansConfig = data;
  } catch (error) {
    console.error("Erro ao carregar configuração dos planos:", error);
    plansConfig = null;
  }
}

function getCurrentKeywordsLimit() {
  if (!savedUser || !plansConfig) {
    return 3;
  }

  if (savedUser.plan === "VIP_BRONZE") {
    return plansConfig.bronze?.keywords_limit ?? 10;
  }

  if (savedUser.plan === "VIP_PRATA") {
    return plansConfig.prata?.keywords_limit ?? 15;
  }

  if (savedUser.plan === "VIP_OURO") {
    return plansConfig.ouro?.keywords_limit ?? 20;
  }

  if (savedUser.plan === "VIP_PREMIUM") {
    return plansConfig.premium?.keywords_limit ?? 30;
  }

  return plansConfig.free?.keywords_limit ?? 3;
}


function showMessage(message, type) {
  adMessage.innerHTML = message;
  adMessage.className = `message-box ${type}`;
}

function clearMessage() {
  adMessage.textContent = "";
  adMessage.innerHTML = "";
  adMessage.className = "message-box";
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

function getVipStatusText(user) {
  if (!user) return "";

  const currentPlanLabel = user.plan_label || getPlanLabel(user.plan);

  if (user.plan === "FREE") {
    return "Plano: FREE";
  }

  if (!user.vip_expires_at) {
    return `Plano: ${currentPlanLabel}`;
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

function getEffectiveUserPlan(user) {
  if (!user || !user.plan) return "FREE";

  const vipPlans = ["VIP_BRONZE", "VIP_PRATA", "VIP_OURO", "VIP_PREMIUM"];
  const isVip = vipPlans.includes(user.plan);

  if (!isVip) return user.plan;

  if (!user.vip_expires_at) return "FREE";

  const expiresAt = new Date(user.vip_expires_at);
  const now = new Date();

  if (expiresAt <= now) {
    return "FREE";
  }

  return user.plan;
}

function getEffectivePlanRulesForUser(user) {
  if (!plansConfig) {
    return {
      can_use_images: false,
      can_use_videos: false
    };
  }

  const effectivePlan = getEffectiveUserPlan(user);

  if (effectivePlan === "VIP_BRONZE") return plansConfig.bronze || {};
  if (effectivePlan === "VIP_PRATA") return plansConfig.prata || {};
  if (effectivePlan === "VIP_OURO") return plansConfig.ouro || {};
  if (effectivePlan === "VIP_PREMIUM") return plansConfig.premium || {};

  return plansConfig.free || {};
}

function updateMediaAccessUI() {
  const currentUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
  const rules = getEffectivePlanRulesForUser(currentUser);

  const canUseImages = !!rules.can_use_images;
  const canUseVideos = !!rules.can_use_videos;

  if (imageUploadBlock) {
    imageUploadBlock.style.display = canUseImages ? "block" : "none";
  }
  if (imageUpgradeMessage) {
    imageUpgradeMessage.style.display = canUseImages ? "none" : "block";
  }

  if (videoUploadBlock) {
    videoUploadBlock.style.display = canUseVideos ? "block" : "none";
  }
  if (videoUpgradeMessage) {
    videoUpgradeMessage.style.display = canUseVideos ? "none" : "block";
  }

  if (!canUseImages && mainImageInput) {
    mainImageInput.value = "";
  }

  if (!canUseVideos && mainVideoInput) {
    mainVideoInput.value = "";
  }
}

function resetSelect(selectElement, placeholder) {
  selectElement.innerHTML = `<option value="">${placeholder}</option>`;
}

function renderUser() {
  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser) {
    userInfo.innerHTML = `
      <strong>Você não está logado.</strong><br>
      Faça login para cadastrar anúncios.
    `;
    return;
  }

	const vipStatusText = getVipStatusText(savedUser);
	const blockedText =
	  savedUser.blocked_until && new Date(savedUser.blocked_until) > new Date()
		? `<br><strong style="color:#dc3545;">Conta bloqueada até ${new Date(savedUser.blocked_until).toLocaleString("pt-BR")}</strong>`
		: "";

	userInfo.innerHTML = `
	  <strong>${savedUser.name}</strong><br>
	  ${savedUser.email}<br>
	  <strong>${vipStatusText}</strong>
	  ${blockedText}
	`;
}

async function refreshSavedUser() {
  if (!savedUser) return;

  try {
    const response = await fetch(`/users/${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) return;

	localStorage.setItem("catalogo_user", JSON.stringify(data));
    savedUser = data;
	renderUser();
	updateKeywordsPlaceholder();
	updateMediaAccessUI();
  } catch (error) {
    console.error("Erro ao atualizar dados do usuário:", error);
  }
}

function renderMyAds(items) {
  myAds.innerHTML = "";

  if (!items.length) {
    myAds.innerHTML = `<div class="muted">Você ainda não cadastrou anúncios.</div>`;
    return;
  }

  items.forEach(item => {
    const div = document.createElement("div");
    div.className = "mini-ad-card";
    div.innerHTML = `
	  <strong>${item.title}</strong><br>

	  ${
		  item.description
			? `<div class="muted" style="margin:6px 0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">
				${item.description}
			  </div>`
			: ""
		}

	  <span class="muted">
		${item.city || ""}
		${item.neighborhood ? " - " + item.neighborhood : ""}
		${item.street ? " - " + item.street : ""}
		${item.number ? ", " + item.number : ""}
		${item.complement ? " - " + item.complement : ""}
		${item.state ? " - " + item.state : ""}
	  </span><br>
		<span class="muted">Telefone: ${item.phone || "Não informado"}</span><br>
		<span class="muted">Plano: ${item.plan}</span><br>
		${
		  item.blocked_until
			? `<span class="muted" style="color:#dc3545;font-weight:bold;">
				 Anúncio bloqueado até ${new Date(item.blocked_until).toLocaleString("pt-BR")}
			   </span><br>`
			: ""
		}
		<br>

	  <div style="display:flex;gap:8px;margin-top:8px;">
		<button type="button" class="edit-btn" data-id="${item.id}">Editar</button>
		<button type="button" class="delete-btn" data-id="${item.id}">Excluir anúncio</button>
	  </div>
	`;
    myAds.appendChild(div);
  });

  document.querySelectorAll(".edit-btn").forEach(button => {
    button.addEventListener("click", () => {
      const adId = Number(button.dataset.id);
      const ad = items.find(item => item.id === adId);
      if (!ad) return;
      startEdit(ad);
    });
  });

  document.querySelectorAll(".delete-btn").forEach(button => {
    button.addEventListener("click", async () => {
      const adId = button.dataset.id;

      const confirmed = confirm("Tem certeza que deseja excluir este anúncio?");
      if (!confirmed) return;

      await deleteAd(adId);
    });
  });
}

function startEdit(ad) {
  editingAdId = ad.id;

  document.getElementById("title").value = ad.title || "";
  document.getElementById("description").value = ad.description || "";
  document.getElementById("phone").value = ad.phone || "";
  document.getElementById("country").value = ad.country || "Brasil";
  document.getElementById("number").value = ad.number || "";
  document.getElementById("complement").value = ad.complement || "";
  document.getElementById("zipcode").value = ad.zipcode || "";
  document.getElementById("keywords").value = (ad.keywords || []).join(", ");

  stateSelect.value = ad.state || "";

  const submitBtn = adForm.querySelector('button[type="submit"]');
  if (submitBtn) {
    submitBtn.textContent = "Salvar alterações";
  }

  if (cancelEditBtn) {
    cancelEditBtn.style.display = "block";
  }

  showMessage("Edite os campos e clique em Salvar alterações.", "success");

  loadCities(ad.state).then(async () => {
    citySelect.value = ad.city || "";

    if (ad.city) {
      await loadNeighborhoods(ad.city, ad.state);
      await loadStreets(ad.city, ad.state, ad.neighborhood || "");
    }

    neighborhoodSelect.value = ad.neighborhood || "";
    streetSelect.value = ad.street || "";
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function resetFormMode() {
  editingAdId = null;
  adForm.reset();
  document.getElementById("country").value = "Brasil";
  document.getElementById("complement").value = "";
  resetSelect(citySelect, "Selecione a cidade");
  resetSelect(neighborhoodSelect, "Selecione o bairro");
  resetSelect(streetSelect, "Selecione a rua");

  const submitBtn = adForm.querySelector('button[type="submit"]');
  if (submitBtn) {
    submitBtn.textContent = "Salvar anúncio";
  }

  if (cancelEditBtn) {
    cancelEditBtn.style.display = "none";
  }
}

if (cancelEditBtn) {
  cancelEditBtn.addEventListener("click", () => {
    resetFormMode();
    clearMessage();
  });
}

async function loadStates() {
  try {
    const response = await fetch("/locations/states");
    const states = await response.json();

    resetSelect(stateSelect, "Selecione o estado");

    if (!response.ok || !Array.isArray(states)) {
      showMessage("Não foi possível carregar os estados.", "error");
      return;
    }

    states.forEach(state => {
      const option = document.createElement("option");
      option.value = state.sigla;
      option.textContent = `${state.nome} (${state.sigla})`;
      stateSelect.appendChild(option);
    });
  } catch (error) {
    console.error("Erro ao carregar estados:", error);
    showMessage("Erro ao carregar estados.", "error");
  }
}

function updateKeywordsPlaceholder() {
  const input = document.getElementById("keywords");

  if (!input || !plansConfig) return;

  const currentUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!currentUser || !currentUser.plan) {
    const freeLimit = plansConfig.free?.keywords_limit ?? 3;
    input.placeholder = `Palavras-chave dos produtos ou serviços (separe por espaço) FREE: até ${freeLimit}`;
    return;
  }

  let currentPlanLabel = "FREE";
  let currentLimit = plansConfig.free?.keywords_limit ?? 3;

  if (currentUser.plan === "VIP_BRONZE") {
    currentPlanLabel = "VIP Bronze";
    currentLimit = plansConfig.bronze?.keywords_limit ?? 10;
  } else if (currentUser.plan === "VIP_PRATA") {
    currentPlanLabel = "VIP Prata";
    currentLimit = plansConfig.prata?.keywords_limit ?? 15;
  } else if (currentUser.plan === "VIP_OURO") {
    currentPlanLabel = "VIP Ouro";
    currentLimit = plansConfig.ouro?.keywords_limit ?? 20;
  } else if (currentUser.plan === "VIP_PREMIUM") {
    currentPlanLabel = "VIP Premium";
    currentLimit = plansConfig.premium?.keywords_limit ?? 30;
  }

  input.placeholder = `Palavras-chave dos produtos ou serviços (separe por espaço) ${currentPlanLabel}: até ${currentLimit}`;
}

async function loadCities(uf) {
  try {
    const response = await fetch(`/locations/cities?uf=${encodeURIComponent(uf)}`);
    const cities = await response.json();

    resetSelect(citySelect, "Selecione a cidade");
    resetSelect(neighborhoodSelect, "Selecione o bairro");
    resetSelect(streetSelect, "Selecione a rua");

    if (!response.ok || !Array.isArray(cities)) {
      showMessage("Não foi possível carregar as cidades.", "error");
      return;
    }

    cities.forEach(city => {
      const option = document.createElement("option");
      option.value = city.nome;
      option.dataset.id = city.id;
      option.textContent = city.nome;
      citySelect.appendChild(option);
    });
  } catch (error) {
    console.error("Erro ao carregar cidades:", error);
    showMessage("Erro ao carregar cidades.", "error");
  }
}

async function loadNeighborhoods(cityName, stateUf) {
  try {
    const params = new URLSearchParams();

    if (cityName) params.append("city", cityName);
    if (stateUf) params.append("state", stateUf);

    const response = await fetch(`/locations/neighborhoods?${params.toString()}`);
    const neighborhoods = await response.json();

    resetSelect(neighborhoodSelect, "Selecione o bairro");

    if (!response.ok || !Array.isArray(neighborhoods)) {
      showMessage("Não foi possível carregar os bairros.", "error");
      return;
    }

    neighborhoods.forEach(neighborhood => {
      const option = document.createElement("option");
      option.value = neighborhood.nome || neighborhood;
      option.textContent = neighborhood.nome || neighborhood;
      neighborhoodSelect.appendChild(option);
    });
  } catch (error) {
    console.error("Erro ao carregar bairros:", error);
    showMessage("Erro ao carregar bairros.", "error");
  }
}

async function loadStreets(cityName, stateUf, neighborhoodName = "") {
  try {
    resetSelect(streetSelect, "Carregando ruas...");

    const tryFetch = async (useNeighborhood) => {
      const params = new URLSearchParams();

      if (cityName) params.append("city", cityName);
      if (stateUf) params.append("state", stateUf);
      if (useNeighborhood && neighborhoodName) {
        params.append("neighborhood", neighborhoodName);
      }

      const response = await fetch(`/locations/streets?${params.toString()}`);
      const streets = await response.json();

      if (!response.ok || !Array.isArray(streets)) {
        return [];
      }

      return streets;
    };

    // 1) tenta com bairro
    let streets = await tryFetch(true);

    // 2) se não achou nada, tenta sem bairro
    if (!streets.length) {
      streets = await tryFetch(false);
    }

    resetSelect(streetSelect, "Selecione a rua");

    streets.forEach(street => {
      const option = document.createElement("option");
      option.value = street.nome || street;
      option.textContent = street.nome || street;
      streetSelect.appendChild(option);
    });

    if (!streets.length) {
      showMessage(
        "Nenhuma rua encontrada para essa localidade. Você pode continuar o cadastro normalmente.",
        "error"
      );
    } else {
      clearMessage();
    }
  } catch (error) {
    console.error("Erro ao carregar ruas:", error);
    showMessage("Erro ao carregar ruas.", "error");
  }
}

async function loadMyAds() {
  if (!savedUser) return;

  try {
    const response = await fetch(`/my-ads/${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) {
      myAds.innerHTML = `<div class="muted">${data.message || "Erro ao carregar anúncios."}</div>`;
      return;
    }

    renderMyAds(data);
  } catch (error) {
    console.error("Erro ao carregar anúncios:", error);
    myAds.innerHTML = `<div class="muted">Erro ao carregar anúncios.</div>`;
  }
}

stateSelect.addEventListener("change", async () => {
  clearMessage();	
  const uf = stateSelect.value;

  resetSelect(citySelect, "Selecione a cidade");
  resetSelect(neighborhoodSelect, "Selecione o bairro");
  resetSelect(streetSelect, "Selecione a rua");

  if (!uf) return;

  await loadCities(uf);
});

citySelect.addEventListener("change", async () => {
  clearMessage();	
  const cityName = citySelect.value;
  const stateUf = stateSelect.value;

  resetSelect(neighborhoodSelect, "Selecione o bairro");
  resetSelect(streetSelect, "Selecione a rua");

  if (!cityName) return;

  await loadNeighborhoods(cityName, stateUf);
  await loadStreets(cityName, stateUf);
});

neighborhoodSelect.addEventListener("change", async () => {
  clearMessage();	
  const cityName = citySelect.value;
  const stateUf = stateSelect.value;
  const neighborhoodName = neighborhoodSelect.value;

  resetSelect(streetSelect, "Selecione a rua");

  if (!cityName) return;

  await loadStreets(cityName, stateUf, neighborhoodName);
});

adForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearMessage();

  if (!requireLogin()) return;

  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser) {
    showMessage("Faça login antes de cadastrar um anúncio.", "error");
    return;
  }

  if (savedUser.blocked_until && new Date(savedUser.blocked_until) > new Date()) {
    showMessage(
      `Sua conta está bloqueada até ${new Date(savedUser.blocked_until).toLocaleString("pt-BR")}.`,
      "error"
    );
    return;
  }

  const keywordsRaw = document.getElementById("keywords").value.trim();

  const keywordsList = keywordsRaw
    ? keywordsRaw
        .split(",")
        .flatMap(part => part.trim().split(/\s+/))
        .map(k => k.trim())
        .filter(Boolean)
    : [];

  const uniqueKeywords = [...new Map(
    keywordsList.map(k => [k.toLowerCase(), k])
  ).values()];

  const maxKeywords = getCurrentKeywordsLimit();

  if (uniqueKeywords.length > maxKeywords) {
    showMessage(
      `Seu plano ${getPlanLabel(savedUser.plan)} permite até ${maxKeywords} palavras-chave.`,
      "error"
    );
    return;
  }

  const mainImageFile = document.getElementById("mainImage").files[0];
  const mainVideoFile = document.getElementById("mainVideo").files[0];

  const formData = new FormData();
  formData.append("user_id", savedUser.id);
  formData.append("title", document.getElementById("title").value.trim());
  formData.append("description", document.getElementById("description").value.trim());
  formData.append("phone", document.getElementById("phone").value.trim());
  formData.append("country", "Brasil");
  formData.append("state", stateSelect.value.trim());
  formData.append("city", citySelect.value.trim());
  formData.append("municipality", citySelect.value.trim());
  formData.append("neighborhood", neighborhoodSelect.value.trim());
  formData.append("street", streetSelect.value.trim());
  formData.append("number", document.getElementById("number").value.trim());
  formData.append("complement", complementInput.value.trim());
  formData.append("zipcode", document.getElementById("zipcode").value.trim());

  uniqueKeywords.forEach(keyword => {
    formData.append("keywords", keyword);
  });

	const effectiveRules = getEffectivePlanRulesForUser(savedUser);

	if (mainImageFile && effectiveRules.can_use_images) {
	  formData.append("main_image", mainImageFile);
	}

	if (mainVideoFile && effectiveRules.can_use_videos) {
	  formData.append("main_video", mainVideoFile);
	}

  try {
    const url = editingAdId ? `/ads/${editingAdId}` : "/ads";
    const method = editingAdId ? "PUT" : "POST";

    const response = await fetch(url, {
      method,
      body: formData
    });

    let data = {};

    try {
      data = await response.json();
    } catch (e) {}

    if (!response.ok) {
      if (response.status === 413) {
        showMessage("O vídeo deve ter no máximo 1 minuto.", "error");
        return;
      }

      if (data.upgrade) {
        showMessage(
          `${data.message}<br><br>
           <button onclick="window.location.href='/vip-page'" class="vip-btn">
             Tornar-se VIP
           </button>`,
          "error"
        );
        return;
      }

      showMessage(data.message || "Erro ao salvar anúncio.", "error");
      return;
    }

    showMessage(
      editingAdId ? "Anúncio atualizado com sucesso." : "Anúncio cadastrado com sucesso.",
      "success"
    );

    resetFormMode();
    loadMyAds();

  } catch (error) {
    console.error("Erro ao salvar anúncio:", error);
    showMessage("Erro ao salvar anúncio.", "error");
  }
});

async function deleteAd(adId) {
  if (!savedUser) {
    showMessage("Faça login para excluir anúncios.", "error");
    return;
  }

  try {
    const response = await fetch(`/ads/${adId}`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        user_id: savedUser.id
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showMessage(data.message || "Erro ao excluir anúncio.", "error");
      return;
    }

    showMessage("Anúncio excluído com sucesso.", "success");
    loadMyAds();
  } catch (error) {
    console.error("Erro ao excluir anúncio:", error);
    showMessage("Erro ao conectar com o servidor.", "error");
  }
}


(async function initCreateAdPage() {
  await loadPlansConfig();

  renderUser();
  updateKeywordsPlaceholder();
  updateMediaAccessUI();
  loadStates();

  if (savedUser) {
    await refreshSavedUser();
    loadMyAds();
  }
})();