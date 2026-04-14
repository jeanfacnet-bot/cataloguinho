const profileForm = document.getElementById("profileForm");
const profileName = document.getElementById("profileName");
const profileEmail = document.getElementById("profileEmail");
const currentPassword = document.getElementById("currentPassword");
const newPassword = document.getElementById("newPassword");
const confirmPassword = document.getElementById("confirmPassword");
const profileMessage = document.getElementById("profileMessage");

let savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

function showProfileMessage(message, type) {
  profileMessage.textContent = message;
  profileMessage.className = `profile-message ${type}`;
}

function clearProfileMessage() {
  profileMessage.textContent = "";
  profileMessage.className = "profile-message";
}

async function loadProfile() {
  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser || !savedUser.id) {
    window.location.href = "/auth-page";
    return;
  }

  try {
    const response = await fetch(`/users/${savedUser.id}`);
    const data = await response.json();

    if (!response.ok) {
      showProfileMessage(data.message || "Erro ao carregar perfil.", "error");
      return;
    }

    profileName.value = data.name || "";
    profileEmail.value = data.email || "";
  } catch (error) {
    console.error("Erro ao carregar perfil:", error);
    showProfileMessage("Erro ao carregar perfil.", "error");
  }
}

profileForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  clearProfileMessage();

  savedUser = JSON.parse(localStorage.getItem("catalogo_user") || "null");

  if (!savedUser || !savedUser.id) {
    window.location.href = "/auth-page";
    return;
  }

  const payload = {
    name: profileName.value.trim(),
    email: profileEmail.value.trim(),
    current_password: currentPassword.value.trim(),
    new_password: newPassword.value.trim(),
    confirm_password: confirmPassword.value.trim()
  };

  try {
    const response = await fetch(`/users/${savedUser.id}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();

    if (!response.ok) {
      showProfileMessage(data.message || "Erro ao atualizar perfil.", "error");
      return;
    }

    if (data.user) {
      localStorage.setItem("catalogo_user", JSON.stringify(data.user));
    }

    currentPassword.value = "";
    newPassword.value = "";
    confirmPassword.value = "";

    showProfileMessage(data.message || "Perfil atualizado com sucesso.", "success");
  } catch (error) {
    console.error("Erro ao atualizar perfil:", error);
    showProfileMessage("Erro ao atualizar perfil.", "error");
  }
});

loadProfile();