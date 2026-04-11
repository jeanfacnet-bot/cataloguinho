const results = document.getElementById("adsResults")

document.getElementById("searchAds").addEventListener("click", async () => {

    const country = document.getElementById("country").value
    const state = document.getElementById("state").value
    const city = document.getElementById("city").value
    const municipality = document.getElementById("municipality").value
    const neighborhood = document.getElementById("neighborhood").value

    const params = new URLSearchParams({
        country,
        state,
        city,
        municipality,
        neighborhood
    })

    const response = await fetch(`/ads?${params}`)
    const ads = await response.json()

    results.innerHTML = ""

    if (ads.length === 0) {
        results.innerHTML = "<p>Nenhuma propaganda encontrada</p>"
        return
    }

    ads.forEach(ad => {

        const div = document.createElement("div")
        div.className = "ad-card"

        div.innerHTML = `
        <h3>${ad.title}</h3>
        <p>${ad.description || ""}</p>
        <p>${ad.city || ""}</p>
        <p>${ad.phone}</p>
        `

        results.appendChild(div)

    })

})