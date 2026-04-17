const registerForm = document.getElementById("registerForm");
const loginForm = document.getElementById("loginForm");
const forgotPasswordForm = document.getElementById("forgotPasswordForm");
const resetPasswordForm = document.getElementById("resetPasswordForm");

const registerMessage = document.getElementById("registerMessage");
const loginMessage = document.getElementById("loginMessage");
const forgotPasswordMessage = document.getElementById("forgotPasswordMessage");
const resetPasswordMessage = document.getElementById("resetPasswordMessage");
const acceptedPrivacyPolicy = document.getElementById("acceptedPrivacyPolicy");

function showMessage(element, message, type) {
  if (!element) return;
  element.textContent = message;
  element.className = `auth-message ${type}`;
}

function normalizeCpf(value) {
  return (value || "").replace(/\D/g, "");
}

function isValidCpf(cpf) {
  cpf = normalizeCpf(cpf);

  if (!cpf || cpf.length !== 11) return false;
  if (/^(\d)\1{10}$/.test(cpf)) return false;

  let sum = 0;
  for (let i = 0; i < 9; i++) {
    sum += parseInt(cpf.charAt(i), 10) * (10 - i);
  }

  let firstDigit = 11 - (sum % 11);
  if (firstDigit >= 10) firstDigit = 0;

  if (firstDigit !== parseInt(cpf.charAt(9), 10)) return false;

  sum = 0;
  for (let i = 0; i < 10; i++) {
    sum += parseInt(cpf.charAt(i), 10) * (11 - i);
  }

  let secondDigit = 11 - (sum % 11);
  if (secondDigit >= 10) secondDigit = 0;

  return secondDigit === parseInt(cpf.charAt(10), 10);
}

if (registerForm) {
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const cpf = document.getElementById("registerCpf").value.trim();
	
	const email = document.getElementById("registerEmail").value.trim();
	const confirmEmail = document.getElementById("confirmEmail").value.trim();

	const password = document.getElementById("registerPassword").value.trim();
	const confirmPassword = document.getElementById("confirmPassword").value.trim();

	if (!isValidCpf(cpf)) {
	  showMessage(registerMessage, "CPF inválido", "error");
	  return;
	}
	
	if (email !== confirmEmail) {
	  showMessage(registerMessage, "Os e-mails não coincidem", "error");
	  return;
	}
	
	if (acceptedPrivacyPolicy && !acceptedPrivacyPolicy.checked) {
	  showMessage(registerMessage, "Você precisa aceitar a Política de Privacidade", "error");
	  return;
	}

	if (password !== confirmPassword) {
	  showMessage(registerMessage, "As senhas não coincidem", "error");
	  return;
	}

	const payload = {
	  name: document.getElementById("registerName").value.trim(),
	  cpf,
	  email,
	  phone: document.getElementById("registerPhone").value.trim(),
	  password,
	  accepted_privacy_policy: acceptedPrivacyPolicy ? acceptedPrivacyPolicy.checked : false
	};

    try {
      const response = await fetch("/register", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (!response.ok) {
        showMessage(registerMessage, data.message || "Erro ao cadastrar", "error");
        return;
      }

      localStorage.setItem("catalogo_user", JSON.stringify(data.user));
      showMessage(registerMessage, "Cadastro realizado com sucesso", "success");
      registerForm.reset();

      setTimeout(() => {
        window.location.href = "/search-page";
      }, 500);
    } catch (error) {
      showMessage(registerMessage, "Erro ao conectar com o servidor", "error");
    }
  });
}

if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
	

    const payload = {
      email: document.getElementById("loginEmail").value.trim(),
      password: document.getElementById("loginPassword").value.trim()
    };

    try {
      const response = await fetch("/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (!response.ok) {
        showMessage(loginMessage, data.message || "Erro ao entrar", "error");
        return;
      }

      localStorage.setItem("catalogo_user", JSON.stringify(data.user));
      showMessage(loginMessage, `Bem-vindo, ${data.user.name}`, "success");
      loginForm.reset();

      setTimeout(() => {
        const redirectAfterLogin = localStorage.getItem("redirect_after_login");

        if (redirectAfterLogin) {
          localStorage.removeItem("redirect_after_login");
          window.location.href = redirectAfterLogin;
          return;
        }

        window.location.href = data.user.is_admin ? "/admin/dashboard-page" : "/search-page";
      }, 500);
    } catch (error) {
      showMessage(loginMessage, "Erro ao conectar com o servidor", "error");
    }
  });
}

if (forgotPasswordForm) {
  forgotPasswordForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const payload = {
      email: document.getElementById("forgotEmail").value.trim()
    };

    try {
      const response = await fetch("/forgot-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (!response.ok) {
        showMessage(forgotPasswordMessage, data.message || "Erro ao solicitar recuperação", "error");
        return;
      }

      showMessage(forgotPasswordMessage, data.message, "success");
      forgotPasswordForm.reset();
    } catch (error) {
      showMessage(forgotPasswordMessage, "Erro ao conectar com o servidor", "error");
    }
  });
}

if (resetPasswordForm) {
  resetPasswordForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";

    const payload = {
      token,
      password: document.getElementById("newPassword").value.trim(),
      confirm_password: document.getElementById("confirmNewPassword").value.trim()
    };

    try {
      const response = await fetch("/reset-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (!response.ok) {
        showMessage(resetPasswordMessage, data.message || "Erro ao redefinir senha", "error");
        return;
      }

      showMessage(resetPasswordMessage, data.message, "success");
      resetPasswordForm.reset();

      setTimeout(() => {
        window.location.href = "/auth-page";
      }, 1200);
    } catch (error) {
      showMessage(resetPasswordMessage, "Erro ao conectar com o servidor", "error");
    }
  });
}