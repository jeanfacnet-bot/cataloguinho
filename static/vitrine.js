const grid =
  document.getElementById(
    "vitrineGrid"
  );

const stateSelect =
  document.getElementById(
    "vitrineState"
  );

const citySelect =
  document.getElementById(
    "vitrineCity"
  );

const neighborhoodSelect =
  document.getElementById(
    "vitrineNeighborhood"
  );

const filterButton =
  document.getElementById(
    "vitrineFilterBtn"
  );

const floatingFilterButton =
  document.getElementById(
    "vitrineFloatingFilterBtn"
  );

const closeFilterButton =
  document.getElementById(
    "vitrineCloseFilterBtn"
  );

const filterPanel =
  document.getElementById(
    "vitrineFilterPanel"
  );

const filterOverlay =
  document.getElementById(
    "vitrineFilterOverlay"
  );

let currentPage = 1;
let hasMorePages = false;
let isLoadingVitrine = false;

const loadMoreButton =
  document.createElement("button");

loadMoreButton.type = "button";
loadMoreButton.id =
  "vitrineLoadMoreBtn";

loadMoreButton.textContent =
  "Carregar mais";

loadMoreButton.style.display =
  "none";

loadMoreButton.style.margin =
  "24px auto";

loadMoreButton.style.padding =
  "12px 24px";

loadMoreButton.style.border =
  "none";

loadMoreButton.style.borderRadius =
  "10px";

loadMoreButton.style.background =
  "#2563eb";

loadMoreButton.style.color =
  "#ffffff";

loadMoreButton.style.fontWeight =
  "700";

loadMoreButton.style.cursor =
  "pointer";

grid.insertAdjacentElement(
  "afterend",
  loadMoreButton
);

function openVitrineFilterPanel() {
  if (
    !filterPanel ||
    !filterOverlay
  ) {
    return;
  }

  filterPanel.classList.add(
    "open"
  );

  filterOverlay.classList.add(
    "open"
  );

  document.body.style.overflow =
    "hidden";

  if (floatingFilterButton) {
    floatingFilterButton.setAttribute(
      "aria-expanded",
      "true"
    );
  }
}

function closeVitrineFilterPanel() {
  if (
    !filterPanel ||
    !filterOverlay
  ) {
    return;
  }

  filterPanel.classList.remove(
    "open"
  );

  filterOverlay.classList.remove(
    "open"
  );

  document.body.style.overflow =
    "";

  if (floatingFilterButton) {
    floatingFilterButton.setAttribute(
      "aria-expanded",
      "false"
    );
  }
}

function resetSelect(
  selectElement,
  placeholder
) {
  selectElement.innerHTML = `
    <option value="">
      ${placeholder}
    </option>
  `;
}

async function loadStates() {
  try {
    resetSelect(
      stateSelect,
      "Todos os estados"
    );

    const response = await fetch(
      "/locations/states"
    );

    const states =
      await response.json();

    if (
      !response.ok ||
      !Array.isArray(states)
    ) {
      throw new Error(
        "Não foi possível carregar os estados."
      );
    }

    states.forEach((state) => {
      const option =
        document.createElement(
          "option"
        );

      option.value = state.sigla;

      option.textContent =
        `${state.nome} (${state.sigla})`;

      stateSelect.appendChild(
        option
      );
    });
  } catch (error) {
    console.error(
      "Erro ao carregar estados:",
      error
    );
  }
}

async function loadCities(state) {
  resetSelect(
    citySelect,
    "Todas as cidades"
  );

  resetSelect(
    neighborhoodSelect,
    "Todos os bairros"
  );

  if (!state) {
    return;
  }

  try {
    const response = await fetch(
      `/locations/cities?uf=${
        encodeURIComponent(state)
      }`
    );

    const cities =
      await response.json();

    if (
      !response.ok ||
      !Array.isArray(cities)
    ) {
      throw new Error(
        "Não foi possível carregar as cidades."
      );
    }

    cities.forEach((city) => {
      const option =
        document.createElement(
          "option"
        );

      option.value = city.nome;
      option.textContent = city.nome;

      citySelect.appendChild(
        option
      );
    });
  } catch (error) {
    console.error(
      "Erro ao carregar cidades:",
      error
    );
  }
}

async function loadNeighborhoods(
  city,
  state
) {
  resetSelect(
    neighborhoodSelect,
    "Todos os bairros"
  );

  if (!city) {
    return;
  }

  try {
    const params =
      new URLSearchParams({
        city,
        state
      });

    const response = await fetch(
      `/locations/neighborhoods?${
        params.toString()
      }`
    );

    const neighborhoods =
      await response.json();

    if (
      !response.ok ||
      !Array.isArray(neighborhoods)
    ) {
      throw new Error(
        "Não foi possível carregar os bairros."
      );
    }

    neighborhoods.forEach(
      (neighborhood) => {
        const name =
          neighborhood.nome ||
          neighborhood;

        const option =
          document.createElement(
            "option"
          );

        option.value = name;
        option.textContent = name;

        neighborhoodSelect.appendChild(
          option
        );
      }
    );
  } catch (error) {
    console.error(
      "Erro ao carregar bairros:",
      error
    );
  }
}

function createVitrineItem(
  ad,
  index
) {
  const item =
    document.createElement("a");

  item.className = "vitrine-item";

  // URL amigável para SEO.
  // Mantém fallback para anúncio antigo sem slug.
  if (ad.slug) {
    item.href =
      `/anuncio/${ad.slug}?from=vitrine`;
  } else {
    item.href =
      `/item/${ad.id}/view?from=vitrine`;
  }

  const imageLoading =
    index < 4 &&
    currentPage === 1
      ? "eager"
      : "lazy";

  const imagePriority =
    index < 4 &&
    currentPage === 1
      ? "high"
      : "low";

  const imageUrl =
    ad.vitrine_image ||
    ad.main_image ||
    "";

  item.innerHTML = `
    <img
      src="${imageUrl}"
      alt="${ad.title || ""}"
      loading="${imageLoading}"
      decoding="async"
      fetchpriority="${imagePriority}"
      width="500"
      height="500"
    >

    <div class="vitrine-caption">

      <div class="vitrine-title">
        ${ad.title || ""}
      </div>

      <div class="vitrine-phone">
        📞 ${
          ad.phone ||
          "Não informado"
        }
      </div>

      <div class="vitrine-address">
        ${ad.city || ""}
        ${
          ad.neighborhood
            ? " - " +
              ad.neighborhood
            : ""
        }
        ${
          ad.street
            ? " - " + ad.street
            : ""
        }
      </div>

    </div>
  `;

  return item;
}

async function loadVitrine({
  reset = false
} = {}) {
  if (isLoadingVitrine) {
    return;
  }

  isLoadingVitrine = true;

  if (reset) {
    currentPage = 1;
    grid.innerHTML =
      "<p>Carregando vitrine...</p>";

    loadMoreButton.style.display =
      "none";
  } else {
    loadMoreButton.disabled = true;

    loadMoreButton.textContent =
      "Carregando...";
  }

  try {
    const params =
      new URLSearchParams({
        page: String(currentPage)
      });

    if (stateSelect.value) {
      params.append(
        "state",
        stateSelect.value
      );
    }

    if (citySelect.value) {
      params.append(
        "city",
        citySelect.value
      );
    }

    if (neighborhoodSelect.value) {
      params.append(
        "neighborhood",
        neighborhoodSelect.value
      );
    }

    const response = await fetch(
      `/vitrine-ads?${
        params.toString()
      }`
    );

    const data =
      await response.json();

    if (
      !response.ok ||
      !data ||
      !Array.isArray(data.items)
    ) {
      throw new Error(
        "Não foi possível carregar a vitrine."
      );
    }

    if (reset) {
      grid.innerHTML = "";
    }

    if (
      reset &&
      !data.items.length
    ) {
      grid.innerHTML = `
        <p>
          Nenhum anúncio encontrado
          para essa região.
        </p>
      `;

      hasMorePages = false;
      loadMoreButton.style.display =
        "none";

      return;
    }

    const fragment =
      document.createDocumentFragment();

    data.items.forEach(
      (ad, index) => {
        fragment.appendChild(
          createVitrineItem(
            ad,
            index
          )
        );
      }
    );

    grid.appendChild(fragment);

    hasMorePages =
      Boolean(data.has_more);

    loadMoreButton.style.display =
      hasMorePages
        ? "block"
        : "none";

  } catch (error) {
    console.error(
      "Erro ao carregar vitrine:",
      error
    );

    if (reset) {
      grid.innerHTML = `
        <p>
          Erro ao carregar vitrine.
        </p>
      `;
    }
  } finally {
    isLoadingVitrine = false;

    loadMoreButton.disabled =
      false;

    loadMoreButton.textContent =
      "Carregar mais";
  }
}

stateSelect.addEventListener(
  "change",
  async () => {
    await loadCities(
      stateSelect.value
    );
  }
);

citySelect.addEventListener(
  "change",
  async () => {
    await loadNeighborhoods(
      citySelect.value,
      stateSelect.value
    );
  }
);

filterButton.addEventListener(
  "click",
  async () => {
    await loadVitrine({
      reset: true
    });

    closeVitrineFilterPanel();
  }
);

loadMoreButton.addEventListener(
  "click",
  async () => {
    if (
      isLoadingVitrine ||
      !hasMorePages
    ) {
      return;
    }

    currentPage += 1;

    await loadVitrine({
      reset: false
    });
  }
);

if (floatingFilterButton) {
  floatingFilterButton.addEventListener(
    "click",
    openVitrineFilterPanel
  );
}

if (closeFilterButton) {
  closeFilterButton.addEventListener(
    "click",
    closeVitrineFilterPanel
  );
}

if (filterOverlay) {
  filterOverlay.addEventListener(
    "click",
    closeVitrineFilterPanel
  );
}

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key === "Escape") {
      closeVitrineFilterPanel();
    }
  }
);

document.addEventListener(
  "DOMContentLoaded",
  async () => {
    await loadStates();

    await loadVitrine({
      reset: true
    });
  }
);