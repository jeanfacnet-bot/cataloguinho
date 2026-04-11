const grid = document.getElementById("vitrineGrid");

async function loadVitrine() {
  try {
    const response = await fetch("/vitrine-ads");
    const ads = await response.json();

    grid.innerHTML = "";

    if (!ads.length) {
      grid.innerHTML = "<p>Nenhuma imagem encontrada.</p>";
      return;
    }

    ads.forEach(ad => {
      const div = document.createElement("div");
      div.className = "vitrine-item";

		div.innerHTML = `
		  <img src="${ad.main_image}" alt="${ad.title}">
		  <div class="vitrine-caption">
			<div class="vitrine-title">${ad.title || ""}</div>
			<div class="vitrine-phone">📞 ${ad.phone || "Não informado"}</div>
			<div class="vitrine-address">
			  ${ad.city || ""}
			  ${ad.neighborhood ? " - " + ad.neighborhood : ""}
			  ${ad.street ? " - " + ad.street : ""}
			</div>
		  </div>
		`;

      div.addEventListener("click", () => {
        window.location.href = `/ads/${ad.id}/page?from=vitrine`;
      });

      grid.appendChild(div);
    });

  } catch (error) {
    console.error("Erro ao carregar vitrine:", error);
    grid.innerHTML = "<p>Erro ao carregar vitrine.</p>";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadVitrine();
});