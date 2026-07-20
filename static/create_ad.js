const adForm = document.getElementById("adForm");
const adMessage = document.getElementById("adMessage");
const userInfo = document.getElementById("userInfo");
const myAds = document.getElementById("myAds");
const adsSummary = document.getElementById("adsSummary");

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
const mapLocationBlock = document.getElementById("mapLocationBlock");
const mapLocationUpgradeMessage = document.getElementById("mapLocationUpgradeMessage");
const mapLocationStatus =
  document.getElementById("mapLocationStatus");

const latitudeInput =
  document.getElementById("latitude");

const longitudeInput =
  document.getElementById("longitude");

const useCurrentLocationBtn =
  document.getElementById("useCurrentLocationBtn");
const keywordInput = document.getElementById("keywordInput");
const addKeywordBtn = document.getElementById("addKeywordBtn");
const keywordTags = document.getElementById("keywordTags");
const keywordsHiddenInput = document.getElementById("keywords");

let selectedKeywords = [];

let adMap = null;
let adMapMarker = null;

let savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
let plansConfig = null;
let editingAdId = null;
const cancelEditBtn = document.getElementById("cancelEditBtn");

function isAdminUser(user) {
  return user && (user.is_admin === true || user.role === "admin" || user.plan === "ADMIN");
}

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
  if (isAdminUser(savedUser)) {
    return Infinity;
  }

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

function getCurrentAdsLimit() {
  if (isAdminUser(savedUser)) {
    return Infinity;
  }

  if (!savedUser || !plansConfig) {
    return 1;
  }

  const effectivePlan = getEffectiveUserPlan(savedUser);

  if (effectivePlan === "VIP_BRONZE") {
    return plansConfig.bronze?.ads_limit ?? 5;
  }

  if (effectivePlan === "VIP_PRATA") {
    return plansConfig.prata?.ads_limit ?? 10;
  }

  if (effectivePlan === "VIP_OURO") {
    return plansConfig.ouro?.ads_limit ?? 20;
  }

  if (effectivePlan === "VIP_PREMIUM") {
    return plansConfig.premium?.ads_limit ?? 50;
  }

  return plansConfig.free?.ads_limit ?? 1;
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

function normalizeKeywordValue(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function syncKeywordsHiddenInput() {
  if (keywordsHiddenInput) {
    keywordsHiddenInput.value = selectedKeywords.join(",");
  }
}

function renderKeywordTags() {
  if (!keywordTags) return;

  keywordTags.innerHTML = "";

  selectedKeywords.forEach((keyword, index) => {
    const tag = document.createElement("span");
    tag.className = "keyword-tag";

    tag.innerHTML = `
      ${keyword}
      <button type="button" class="keyword-remove" data-index="${index}" title="Remover palavra-chave">×</button>
    `;

    keywordTags.appendChild(tag);
  });

  document.querySelectorAll(".keyword-remove").forEach(button => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.index);
      selectedKeywords.splice(index, 1);
      syncKeywordsHiddenInput();
      renderKeywordTags();
      updateKeywordsPlaceholder();
    });
  });

  syncKeywordsHiddenInput();
}

function addKeywordFromInput() {
  if (!keywordInput) return;

  clearMessage();

  const rawValue = normalizeKeywordValue(keywordInput.value);

  if (!rawValue) return;

  const values = rawValue
    .split(",")
    .flatMap(part => part.trim().split(/\s+/))
    .map(item => normalizeKeywordValue(item))
    .filter(Boolean);

  const maxKeywords = getCurrentKeywordsLimit();

  for (const value of values) {
    const exists = selectedKeywords.some(
      item => item.toLowerCase() === value.toLowerCase()
    );

    if (exists) continue;

    if (selectedKeywords.length >= maxKeywords) {
      showMessage(
        `Seu plano ${getPlanLabel(savedUser?.plan)} permite até ${maxKeywords} palavras-chave.`,
        "error"
      );
      break;
    }

    selectedKeywords.push(value);
  }

  keywordInput.value = "";
  renderKeywordTags();
  updateKeywordsPlaceholder();
}

function setKeywordsFromArray(items) {
  selectedKeywords = [];

  (items || []).forEach(item => {
    const value = normalizeKeywordValue(item);

    if (!value) return;

    const exists = selectedKeywords.some(
      keyword => keyword.toLowerCase() === value.toLowerCase()
    );

    if (!exists) {
      selectedKeywords.push(value);
    }
  });

  renderKeywordTags();
  updateKeywordsPlaceholder();
}

function getPlanLabel(plan) {
  const labels = {
    ADMIN: "Administrador",
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
  
  if (isAdminUser(user)) {
    return "Tipo de conta: Administrador";
  }  

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
  if (isAdminUser(user)) {
    return {
      ads_limit: Infinity,
      keywords_limit: Infinity,
      can_use_images: true,
      can_use_videos: true,
      can_appear_in_vip_list: false,
      can_show_full_details: true,
      can_use_vitrine: true,
      can_use_location: true
    };
  }

  if (!plansConfig) {
    return {
      can_use_images: false,
      can_use_videos: false,
      can_use_location: false
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

function updateLocationAccessUI() {
  const currentUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
  const rules = getEffectivePlanRulesForUser(currentUser);
  const canUseLocation = !!rules.can_use_location;

  if (mapLocationBlock) {
    mapLocationBlock.style.display = canUseLocation ? "block" : "none";
  }

  if (mapLocationUpgradeMessage) {
    mapLocationUpgradeMessage.style.display = canUseLocation ? "none" : "block";
  }

  if (!canUseLocation) {
    if (latitudeInput) latitudeInput.value = "";
    if (longitudeInput) longitudeInput.value = "";
    return;
  }

  setTimeout(initAdMap, 200);
}

function initAdMap() {
  if (!document.getElementById("adMap")) return;
  if (adMap) {
    adMap.invalidateSize();
    return;
  }

  adMap = L.map("adMap").setView([-15.7801, -47.9292], 5);
  
  locateUserOnMap();

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap"
  }).addTo(adMap);

  adMap.on("click", function (event) {
    setMapMarker(event.latlng.lat, event.latlng.lng);
  });
}

function setMapMarker(lat, lng) {
  if (!adMap) return;

  const safeLat = Number(lat);
  const safeLng = Number(lng);

  if (!Number.isFinite(safeLat) || !Number.isFinite(safeLng)) return;

  if (adMapMarker) {
    adMapMarker.setLatLng([safeLat, safeLng]);
  } else {
    adMapMarker = L.marker([safeLat, safeLng]).addTo(adMap);
  }

  latitudeInput.value = safeLat.toFixed(7);
  longitudeInput.value = safeLng.toFixed(7);

  if (mapLocationStatus) {
    mapLocationStatus.textContent = `Localização marcada: ${safeLat.toFixed(7)}, ${safeLng.toFixed(7)}`;
  }
}

function locateUserOnMap() {
  if (!navigator.geolocation) {
    if (mapLocationStatus) {
      mapLocationStatus.textContent =
        "Seu navegador não oferece suporte à localização.";
    }

    return;
  }

  if (!adMap) {
    initAdMap();
  }

  if (useCurrentLocationBtn) {
    useCurrentLocationBtn.disabled = true;
    useCurrentLocationBtn.textContent =
      "📍 Localizando...";
  }

  if (mapLocationStatus) {
    mapLocationStatus.textContent =
      "Obtendo sua localização atual...";
  }

  navigator.geolocation.getCurrentPosition(
    function (position) {
      const latitude = position.coords.latitude;
      const longitude = position.coords.longitude;

      if (!adMap) {
        initAdMap();
      }

      setMapMarker(latitude, longitude);

      adMap.setView(
        [latitude, longitude],
        17
      );

      if (mapLocationStatus) {
        mapLocationStatus.textContent =
          "Localização atual marcada. Você pode clicar no mapa para ajustar.";
      }

      if (useCurrentLocationBtn) {
        useCurrentLocationBtn.disabled = false;
        useCurrentLocationBtn.textContent =
          "📍 Atualizar minha localização";
      }
    },

    function (error) {
      let errorMessage =
        "Não foi possível obter sua localização.";

      if (error.code === error.PERMISSION_DENIED) {
        errorMessage =
          "Permissão de localização negada. Libere a localização nas configurações do navegador.";
      }

      if (error.code === error.POSITION_UNAVAILABLE) {
        errorMessage =
          "Sua localização não está disponível neste momento.";
      }

      if (error.code === error.TIMEOUT) {
        errorMessage =
          "A localização demorou muito para responder. Tente novamente.";
      }

      if (mapLocationStatus) {
        mapLocationStatus.textContent = errorMessage;
      }

      if (useCurrentLocationBtn) {
        useCurrentLocationBtn.disabled = false;
        useCurrentLocationBtn.textContent =
          "📍 Tentar novamente";
      }

      console.error(
        "Erro ao obter localização:",
        error
      );
    },

    {
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 0
    }
  );
}

if (useCurrentLocationBtn) {
  useCurrentLocationBtn.addEventListener(
    "click",
    function () {
      locateUserOnMap();
    }
  );
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

function renderAdsSummary(items = []) {
  if (!adsSummary) return;

  const currentUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!currentUser || !plansConfig) {
    adsSummary.innerHTML = `<div class="muted">Não foi possível carregar o resumo do plano.</div>`;
    return;
  }

  const usedAds = Array.isArray(items) ? items.length : 0;

	if (isAdminUser(currentUser)) {
	  adsSummary.innerHTML = `
		<strong>Tipo de conta:</strong> Administrador<br>
		<strong>Anúncios cadastrados:</strong> ${usedAds}<br>
		<strong>Limite:</strong> ilimitado
	  `;
	  return;
	}

	const effectivePlan = getEffectiveUserPlan(currentUser);
	const currentPlanLabel = getPlanLabel(effectivePlan);
	const adsLimit = getCurrentAdsLimit();
	const remainingAds = Math.max(adsLimit - usedAds, 0);

	adsSummary.innerHTML = `
	  <strong>Plano atual:</strong> ${currentPlanLabel}<br>
	  <strong>Anúncios cadastrados:</strong> ${usedAds} de ${adsLimit}<br>
	  <strong>Disponíveis para cadastrar:</strong> ${remainingAds}
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
	updateLocationAccessUI();
  } catch (error) {
    console.error("Erro ao atualizar dados do usuário:", error);
  }
}

function renderMyAds(items) {
  myAds.innerHTML = "";
  renderAdsSummary(items);

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

		<div class="ad-actions-row">
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
  setKeywordsFromArray(ad.keywords || []);

  stateSelect.value = ad.state || "";
  
	if (latitudeInput) latitudeInput.value = ad.latitude || "";
	if (longitudeInput) longitudeInput.value = ad.longitude || "";

	if (ad.latitude && ad.longitude) {
	  setTimeout(() => {
		initAdMap();
		setMapMarker(ad.latitude, ad.longitude);
		adMap.setView([ad.latitude, ad.longitude], 16);
	  }, 300);
	}

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
    
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

	if (addKeywordBtn) {
	  addKeywordBtn.addEventListener("click", addKeywordFromInput);
	}

	if (keywordInput) {
	  keywordInput.addEventListener("keydown", (event) => {
		if (event.key === "Enter" || event.key === ",") {
		  event.preventDefault();
		  addKeywordFromInput();
		}
	  });

	  keywordInput.addEventListener("blur", () => {
		addKeywordFromInput();
	  });
	}

function resetFormMode() {
  editingAdId = null;
  adForm.reset();
  setKeywordsFromArray([]);
  document.getElementById("country").value = "Brasil";
  document.getElementById("complement").value = "";
  resetSelect(citySelect, "Selecione a cidade");
  resetSelect(neighborhoodSelect, "Selecione o bairro");
  if (streetSelect) {
    resetSelect(streetSelect, "Selecione a rua");
  }

  const submitBtn = adForm.querySelector('button[type="submit"]');
  if (submitBtn) {
    submitBtn.textContent = "Salvar anúncio";
  }

  if (cancelEditBtn) {
    cancelEditBtn.style.display = "none";
  }
  
    if (latitudeInput) {
	  latitudeInput.value = "";
	}

	if (longitudeInput) {
	  longitudeInput.value = "";
	}

	if (adMapMarker && adMap) {
	  adMap.removeLayer(adMapMarker);
	  adMapMarker = null;
	}

	if (mapLocationStatus) {
	  mapLocationStatus.textContent =
		"Clique no mapa ou use sua localização atual.";
	}

	if (useCurrentLocationBtn) {
	  useCurrentLocationBtn.disabled = false;
	  useCurrentLocationBtn.textContent =
		"📍 Usar minha localização atual";
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
  if (!plansConfig) return;

  const currentUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");
  const maxKeywords = getCurrentKeywordsLimit();
  const used = selectedKeywords.length;
  const remaining = Math.max(maxKeywords - used, 0);

  if (keywordInput) {
    keywordInput.placeholder = `Digite uma palavra-chave (${remaining} restantes)`;
    keywordInput.disabled = remaining <= 0;
  }

  const keywordHelp = document.getElementById("keywordHelp");

  if (keywordHelp) {
    keywordHelp.textContent = `Você adicionou ${used} de ${maxKeywords} palavras-chave permitidas pelo seu plano.`;
  }

  if (addKeywordBtn) {
    addKeywordBtn.disabled = remaining <= 0;
    addKeywordBtn.textContent = remaining <= 0 ? "Limite atingido" : "Adicionar";
  }
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
  return;
}

async function loadMyAds() {
  if (!savedUser) return;

  try {
    const response = await fetch(`/my-ads/${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) {
	  myAds.innerHTML = `<div class="muted">${data.message || "Erro ao carregar anúncios."}</div>`;

	  if (adsSummary) {
		adsSummary.innerHTML = `<div class="muted">Não foi possível carregar o resumo dos anúncios.</div>`;
	  }

	  return;
	}

	renderMyAds(data);

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

  if (streetSelect) {
    resetSelect(streetSelect, "Selecione a rua");
  }

  if (!cityName) return;

  await loadNeighborhoods(cityName, stateUf);
});

neighborhoodSelect.addEventListener("change", () => {
  clearMessage();

  if (streetSelect) {
    resetSelect(streetSelect, "Selecione a rua");
  }
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

	addKeywordFromInput();

	const uniqueKeywords = [...new Map(
	  selectedKeywords.map(k => [k.toLowerCase(), k])
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

  if (citySelect.value) {
    formData.append("city", citySelect.value.trim());
    formData.append("municipality", citySelect.value.trim());
  } else {
    formData.append("city", "");
    formData.append("municipality", "");
  }
  formData.append("neighborhood", neighborhoodSelect.value.trim());
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
    const url = editingAdId ? `/anuncios/${editingAdId}` : "/ads";
    const method = editingAdId ? "PUT" : "POST";
	
	const rules = getEffectivePlanRulesForUser(savedUser);

	if (rules.can_use_location && latitudeInput && longitudeInput) {
	  formData.append("latitude", latitudeInput.value);
	  formData.append("longitude", longitudeInput.value);
	}

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
    const response = await fetch(`/anuncios/${adId}`, {
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
  updateLocationAccessUI();
  loadStates();

  if (savedUser) {
    await refreshSavedUser();
    loadMyAds();
  }
})();