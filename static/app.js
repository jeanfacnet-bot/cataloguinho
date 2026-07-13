const termInput = document.getElementById("term");
const stateSelect = document.getElementById("state");
const citySelect = document.getElementById("city");
const neighborhoodSelect = document.getElementById("neighborhood");
const streetSelect = document.getElementById("street");
const complementInput = document.getElementById("complement");
const searchBtn = document.getElementById("searchBtn");
const resultsContainer = document.getElementById("results");
const resultCount = document.getElementById("resultCount");
let currentController = null;
let lastSearchResults = [];

const SEARCH_STATE_KEY = "catalogo_search_state";

const locationCache = {
  states: null,
  cities: new Map(),
  neighborhoods: new Map(),
  streets: new Map()
};

console.log("app.js carregado");
console.log({
  termInput,
  stateSelect,
  citySelect,
  neighborhoodSelect,
  streetSelect,
  complementInput,
  searchBtn,
  resultsContainer,
  resultCount
});

function getPlanStar(plan) {
  const stars = {
    VIP_BRONZE: '<span class="vip-star star-bronze" title="VIP Bronze">★</span>',
    VIP_PRATA: '<span class="vip-star star-prata" title="VIP Prata">★</span>',
    VIP_OURO: '<span class="vip-star star-ouro" title="VIP Ouro">★</span>',
    VIP_PREMIUM: '<span class="vip-star star-premium" title="VIP Premium">★</span>'
  };

  return stars[plan] || "";
}

function getSavedUserSafely() {
  try {
    const rawUser =
      localStorage.getItem("catalogo_user");

    if (!rawUser) {
      return null;
    }

    return JSON.parse(rawUser);
  } catch (error) {
    console.warn(
      "Dados inválidos do usuário no navegador:",
      error
    );

    localStorage.removeItem("catalogo_user");
    return null;
  }
}

const savedUser = getSavedUserSafely();

function getSearchFormState() {
  return {
    term: termInput ? termInput.value.trim() : "",
    state: stateSelect ? stateSelect.value.trim() : "",
    city: citySelect ? citySelect.value.trim() : "",
    neighborhood: neighborhoodSelect ? neighborhoodSelect.value.trim() : "",
    complement: complementInput ? complementInput.value.trim() : "",
    scrollY: window.scrollY || 0
  };
}

function saveSearchState(results = lastSearchResults) {
  try {
    const state = {
      filters: getSearchFormState(),
      results: Array.isArray(results) ? results : [],
      savedAt: Date.now()
    };

    sessionStorage.setItem(
      SEARCH_STATE_KEY,
      JSON.stringify(state)
    );

    return true;
  } catch (error) {
    console.warn("Não foi possível salvar a pesquisa:", error);

    try {
      sessionStorage.removeItem(SEARCH_STATE_KEY);
    } catch (removeError) {
      console.warn(
        "Também não foi possível limpar o estado da pesquisa:",
        removeError
      );
    }

    return false;
  }
}

async function restoreSearchStateIfAny() {
  const rawState = sessionStorage.getItem(SEARCH_STATE_KEY);

  if (!rawState) {
    return false;
  }

  let savedState = null;

  try {
    savedState = JSON.parse(rawState);
  } catch (error) {
    sessionStorage.removeItem(SEARCH_STATE_KEY);
    return false;
  }

  const filters = savedState.filters || {};
  const results = Array.isArray(savedState.results) ? savedState.results : [];

  await loadStates();

  if (termInput) {
    termInput.value = filters.term || "";
  }

  if (stateSelect) {
    stateSelect.value = filters.state || "";
  }

  if (filters.state) {
    await loadCities(filters.state);
  }

  if (citySelect) {
    citySelect.value = filters.city || "";
  }

  if (filters.city) {
    await loadNeighborhoods(filters.city, filters.state || "");
  }

  if (neighborhoodSelect) {
    neighborhoodSelect.value = filters.neighborhood || "";
  }

  if (complementInput) {
    complementInput.value = filters.complement || "";
  }

  lastSearchResults = results;
  renderResults(results);

  setTimeout(() => {
    window.scrollTo(0, Number(filters.scrollY || 0));
  }, 100);

  return true;
}

function getAppVersion() {
  return (
    document.documentElement.dataset.appVersion ||
    "local"
  );
}

function openAdDetailsFromSearch(adId) {
  try {
    saveSearchState(lastSearchResults);
  } catch (error) {
    console.warn(
      "Não foi possível salvar o estado da pesquisa:",
      error
    );
  }

  const detailsUrl = new URL(
    `/item/${adId}/view`,
    window.location.origin
  );

  detailsUrl.searchParams.set("from", "search");
  detailsUrl.searchParams.set("v", getAppVersion());

  window.location.href = detailsUrl.toString();
}

function shareAdOnWhatsApp(adId, adTitle) {
  const adUrl =
	`${window.location.origin}/item/${adId}/view?from=share`;

  const message = [
    "Olha este anúncio no CataLogin:",
    `"${adTitle || "Anúncio"}"`,
    adUrl
  ].join("\n");

  const whatsappUrl =
    `https://wa.me/?text=${encodeURIComponent(message)}`;

  window.open(
    whatsappUrl,
    "_blank",
    "noopener,noreferrer"
  );
}


function resetSelect(selectElement, placeholder) {
  if (!selectElement) return;
  selectElement.innerHTML = `<option value="">${placeholder}</option>`;
}

function renderResults(items) {
  if (!resultsContainer || !resultCount) {
    console.error("resultsContainer ou resultCount não encontrados");
    return;
  }

  resultsContainer.textContent = "";
  resultCount.textContent = `${items.length} encontrados`;

  if (!items.length) {
    resultsContainer.innerHTML = `<div class="muted">Nenhum resultado encontrado.</div>`;
    return;
  }

	const fragment = document.createDocumentFragment();

	items.forEach(item => {
	  const card = document.createElement("div");
	  card.className = "result-card";

	  card.innerHTML = `
		<div class="result-info">
		  <h3 class="ad-title-row">
			${item.title || ""} ${getPlanStar(item.plan)}
		  </h3>

		  <div class="muted">
			${item.city || ""}
			${item.neighborhood ? " - " + item.neighborhood : ""}
			${item.street ? " - " + item.street : ""}
			${item.number ? ", " + item.number : ""}
			${item.complement ? " - " + item.complement : ""}
			${item.state ? " - " + item.state : ""}
		  </div>

			<div class="result-actions">
			  ${
				item.can_show_full_details
				  ? `
					<button
					  type="button"
					  onclick="openAdDetailsFromSearch(${item.id})"
					>
					  Ver detalhes
					</button>

					<button
					  type="button"
					  class="share-whatsapp-btn"
					  data-ad-id="${item.id}"
					  data-ad-title="${encodeURIComponent(item.title || "Anúncio")}"
					>
					  💬 Compartilhar
					</button>
				  `
				  : ""
			  }
			</div>

		  <div id="reportBox-${item.id}" class="report-box">
			<select id="reportReason-${item.id}" class="report-reason-select">
			  <option value="">Selecione um motivo</option>
			  <option value="Produto ou serviço não existe">Produto ou serviço não existe</option>
			  <option value="Conteúdo inadequado">Conteúdo inadequado</option>
			  <option value="Informações falsas ou enganosas">Informações falsas ou enganosas</option>
			  <option value="Golpe ou tentativa de fraude">Golpe ou tentativa de fraude</option>
			  <option value="Spam ou anúncio repetido">Spam ou anúncio repetido</option>
			  <option value="Telefone ou contato inválido">Telefone ou contato inválido</option>
			  <option value="Endereço incorreto">Endereço incorreto</option>
			  <option value="Outro">Outro</option>
			</select>

			<textarea
			  id="reportText-${item.id}"
			  maxlength="300"
			  placeholder="Descreva melhor o problema (opcional)"
			></textarea>

			<div class="report-box-actions">
			  <button type="button" class="report-send-btn" onclick="sendReport(${item.id})">Enviar denúncia</button>
			  <button type="button" class="report-cancel-btn" onclick="toggleReportBox(${item.id}, false)">Cancelar</button>
			</div>
		  </div>
		</div>

		${
		  item.main_image
			? `
			  <div class="result-image">
				<img src="${item.main_image}" alt="${item.title}" loading="lazy">
			  </div>
			`
			: ""
		}

		<div class="report-side">
		  <button type="button" class="report-btn" onclick="toggleReportBox(${item.id})">Denunciar</button>
		</div>
	  `;

	  fragment.appendChild(card);
	});

resultsContainer.appendChild(fragment);

resultsContainer
  .querySelectorAll(".share-whatsapp-btn")
  .forEach(button => {
    button.addEventListener("click", () => {
      const adId = button.dataset.adId;
      const adTitle = decodeURIComponent(
        button.dataset.adTitle || "Anúncio"
      );

      shareAdOnWhatsApp(adId, adTitle);
    });
  });
}

function toggleReportBox(adId, forceState = null) {
  const box = document.getElementById(`reportBox-${adId}`);
  if (!box) return;

  if (forceState === true) {
    box.style.display = "block";
    return;
  }

  if (forceState === false) {
    box.style.display = "none";
    return;
  }

  box.style.display = box.style.display === "block" ? "none" : "block";
}

async function sendReport(adId) {
  if (!(await requireLogin())) return;

  const select = document.getElementById(`reportReason-${adId}`);
  const textArea = document.getElementById(`reportText-${adId}`);

  if (!select || !textArea) return;

  const selectedReason = select.value.trim();
  const details = textArea.value.trim();

  if (!selectedReason) {
    alert("Selecione o motivo da denúncia.");
    return;
  }

  let finalReason = selectedReason;

  if (details) {
    finalReason += ` | Detalhes: ${details}`;
  }

  try {
    const response = await fetch("/reports", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        ad_id: adId,
        reason: finalReason
      })
    });

    const data = await response.json();

    if (!response.ok) {
      alert(data.message || "Erro ao enviar denúncia.");
      return;
    }

    alert("Denúncia enviada com sucesso.");
    select.value = "";
    textArea.value = "";
    toggleReportBox(adId, false);
  } catch (error) {
    console.error("Erro ao enviar denúncia:", error);
    alert("Erro ao enviar denúncia.");
  }
}

async function loadStates() {
  try {
    resetSelect(stateSelect, "Selecione o estado");

    if (Array.isArray(locationCache.states)) {
      locationCache.states.forEach(state => {
        const option = document.createElement("option");
        option.value = state.sigla;
        option.textContent = `${state.nome} (${state.sigla})`;
        stateSelect.appendChild(option);
      });
      return;
    }

    const response = await fetch("/locations/states");
    const states = await response.json();

    if (!response.ok || !Array.isArray(states)) {
      console.error("Não foi possível carregar os estados.", states);
      return;
    }

    locationCache.states = states;

    states.forEach(state => {
      const option = document.createElement("option");
      option.value = state.sigla;
      option.textContent = `${state.nome} (${state.sigla})`;
      stateSelect.appendChild(option);
    });
  } catch (error) {
    console.error("Erro ao carregar estados:", error);
  }
}

async function loadCities(uf) {
  try {
    resetSelect(citySelect, "Selecione a cidade");
    resetSelect(neighborhoodSelect, "Selecione o bairro");
    if (streetSelect) {
	  resetSelect(streetSelect, "Selecione a rua");
	}

    if (!uf) return;

    const cacheKey = uf;

    if (locationCache.cities.has(cacheKey)) {
      const cachedCities = locationCache.cities.get(cacheKey);

      cachedCities.forEach(city => {
        const option = document.createElement("option");
        option.value = city.nome;
        option.textContent = city.nome;
        citySelect.appendChild(option);
      });
      return;
    }

    const response = await fetch(`/locations/cities?uf=${encodeURIComponent(uf)}`);
    const cities = await response.json();

    if (!response.ok || !Array.isArray(cities)) {
      console.error("Não foi possível carregar as cidades.", cities);
      return;
    }

    locationCache.cities.set(cacheKey, cities);

    cities.forEach(city => {
      const option = document.createElement("option");
      option.value = city.nome;
      option.textContent = city.nome;
      citySelect.appendChild(option);
    });
  } catch (error) {
    console.error("Erro ao carregar cidades:", error);
  }
}

async function loadNeighborhoods(cityName, stateUf) {
  try {
    resetSelect(neighborhoodSelect, "Selecione o bairro");

    if (!cityName) return;

    const cacheKey = `${stateUf}::${cityName}`;

    if (locationCache.neighborhoods.has(cacheKey)) {
      const cachedNeighborhoods = locationCache.neighborhoods.get(cacheKey);

      cachedNeighborhoods.forEach(neighborhood => {
        const nome = neighborhood.nome || neighborhood;
        const option = document.createElement("option");
        option.value = nome;
        option.textContent = nome;
        neighborhoodSelect.appendChild(option);
      });
      return;
    }

    const params = new URLSearchParams();
    if (cityName) params.append("city", cityName);
    if (stateUf) params.append("state", stateUf);

    const response = await fetch(`/locations/neighborhoods?${params.toString()}`);
    const neighborhoods = await response.json();

    if (!response.ok || !Array.isArray(neighborhoods)) {
      console.error("Não foi possível carregar os bairros.", neighborhoods);
      return;
    }

    locationCache.neighborhoods.set(cacheKey, neighborhoods);

    neighborhoods.forEach(neighborhood => {
      const nome = neighborhood.nome || neighborhood;
      const option = document.createElement("option");
      option.value = nome;
      option.textContent = nome;
      neighborhoodSelect.appendChild(option);
    });
  } catch (error) {
    console.error("Erro ao carregar bairros:", error);
  }
}

async function loadStreets(cityName, stateUf, neighborhoodName = "") {
  return;
}

async function searchAds() {
  console.log("Botão pesquisar clicado");

  try {
    const params = new URLSearchParams();

    const term = termInput?.value.trim() || "";
    const state = stateSelect?.value.trim() || "";
    const city = citySelect?.value.trim() || "";
    const neighborhood = neighborhoodSelect?.value.trim() || "";
    const street = "";
	const complement = complementInput?.value.trim() || "";

    if (term) params.append("term", term);
    if (state) params.append("state", state);
    if (city) params.append("city", city);
    if (neighborhood) params.append("neighborhood", neighborhood);
    
	if (complement) params.append("complement", complement);

    const url = `/search?${params.toString()}`;
    console.log("Buscando:", url);
	resultsContainer.innerHTML = `<div class="muted">Buscando anúncios...</div>`;
	resultCount.textContent = "Carregando...";

	if (currentController) {
	  currentController.abort();
	}

	currentController = new AbortController();
    const response = await fetch(url, {
	  signal: currentController.signal
	});
    const data = await response.json();

    console.log("Resposta /search:", response.status, data);

	if (!response.ok || !Array.isArray(data)) {
	  console.error("Erro na pesquisa:", data);
	  lastSearchResults = [];
	  renderResults([]);
	  saveSearchState([]);
	  return;
	}

	lastSearchResults = data;
	renderResults(data);
	saveSearchState(data);

	setTimeout(() => {
	  const firstResult = document.querySelector(".result-card");

	  if (firstResult) {
		firstResult.scrollIntoView({
		  behavior: "smooth",
		  block: "start"
		});
	  } else if (resultsContainer) {
		resultsContainer.scrollIntoView({
		  behavior: "smooth",
		  block: "start"
		});
	  }
	}, 100);

  } catch (error) {
    if (error.name === "AbortError") return;
	console.error("Erro ao pesquisar anúncios:", error);
    renderResults([]);
  }
}

if (stateSelect) {
  stateSelect.addEventListener("change", async () => {
    const uf = stateSelect.value;

    resetSelect(citySelect, "Selecione a cidade");
    resetSelect(neighborhoodSelect, "Selecione o bairro");
    if (streetSelect) {
	  resetSelect(streetSelect, "Selecione a rua");
	}

    if (!uf) return;

    await loadCities(uf);
  });
}

if (citySelect) {
  citySelect.addEventListener("change", async () => {
    const cityName = citySelect.value;
    const stateUf = stateSelect.value;

    resetSelect(neighborhoodSelect, "Selecione o bairro");

    if (streetSelect) {
      resetSelect(streetSelect, "Selecione a rua");
    }

    if (!cityName) return;

    await loadNeighborhoods(cityName, stateUf);
  });
}

if (neighborhoodSelect) {
  neighborhoodSelect.addEventListener("change", () => {
    if (streetSelect) {
      resetSelect(streetSelect, "Selecione a rua");
    }
  });
}

if (streetSelect) {
  streetSelect.addEventListener("focus", async () => {
    const cityName = citySelect.value;
    const stateUf = stateSelect.value;
    const neighborhoodName = neighborhoodSelect.value;

    if (!cityName) return;

    const hasOnlyPlaceholder = streetSelect.options.length <= 1;

    if (!hasOnlyPlaceholder) return;

    await loadStreets(cityName, stateUf, neighborhoodName);
  });
}

if (searchBtn) {
  searchBtn.addEventListener("click", searchAds);
} else {
  console.error("searchBtn não encontrado");
}

async function initSearchPage() {
  const restored = await restoreSearchStateIfAny();

  if (restored) {
    return;
  }

  await loadStates();
  await searchAds();
}

initSearchPage();