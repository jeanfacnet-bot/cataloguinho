const grid =
  document.getElementById("vitrineGrid");

const stateSelect =
  document.getElementById("vitrineState");

const citySelect =
  document.getElementById("vitrineCity");

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

function openVitrineFilterPanel() {
  if (!filterPanel || !filterOverlay) {
    return;
  }

  filterPanel.classList.add("open");
  filterOverlay.classList.add("open");

  document.body.style.overflow = "hidden";

  if (floatingFilterButton) {
    floatingFilterButton.setAttribute(
      "aria-expanded",
      "true"
    );
  }
}

function closeVitrineFilterPanel() {
  if (!filterPanel || !filterOverlay) {
    return;
  }

  filterPanel.classList.remove("open");
  filterOverlay.classList.remove("open");

  document.body.style.overflow = "";

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
      "/locations/states",
      {
        cache: "no-store"
      }
    );

    const states = await response.json();

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
        document.createElement("option");

      option.value = state.sigla;
      option.textContent =
        `${state.nome} (${state.sigla})`;

      stateSelect.appendChild(option);
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
      }`,
      {
        cache: "no-store"
      }
    );

    const cities = await response.json();

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
        document.createElement("option");

      option.value = city.nome;
      option.textContent = city.nome;

      citySelect.appendChild(option);
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
    const params = new URLSearchParams({
      city,
      state
    });

    const response = await fetch(
      `/locations/neighborhoods?${
        params.toString()
      }`,
      {
        cache: "no-store"
      }
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
          document.createElement("option");

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

async function loadVitrine() {
  try {
    const params = new URLSearchParams();

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

    grid.innerHTML =
      "<p>Carregando vitrine...</p>";

    const response = await fetch(
      `/vitrine-ads?${params.toString()}`,
      {
        cache: "no-store"
      }
    );

    const ads = await response.json();

    if (
      !response.ok ||
      !Array.isArray(ads)
    ) {
      throw new Error(
        "Não foi possível carregar a vitrine."
      );
    }

    grid.innerHTML = "";

    if (!ads.length) {
      grid.innerHTML = `
        <p>
          Nenhum anúncio encontrado
          para essa região.
        </p>
      `;
      return;
    }

    ads.forEach((ad) => {
      const div =
        document.createElement("div");

      div.className = "vitrine-item";

      div.innerHTML = `
        <img
          src="${ad.main_image}"
          alt="${ad.title || ""}"
          loading="lazy"
        >

        <div class="vitrine-caption">
          <div class="vitrine-title">
            ${ad.title || ""}
          </div>

          <div class="vitrine-phone">
            📞 ${ad.phone || "Não informado"}
          </div>

          <div class="vitrine-address">
            ${ad.city || ""}
            ${
              ad.neighborhood
                ? " - " + ad.neighborhood
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

      div.addEventListener(
        "click",
        () => {
          window.location.href =
            `/item/${ad.id}/view?from=vitrine`;
        }
      );

      grid.appendChild(div);
    });
  } catch (error) {
    console.error(
      "Erro ao carregar vitrine:",
      error
    );

    grid.innerHTML = `
      <p>Erro ao carregar vitrine.</p>
    `;
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
    await loadVitrine();
    closeVitrineFilterPanel();
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
    await loadVitrine();
  }
);