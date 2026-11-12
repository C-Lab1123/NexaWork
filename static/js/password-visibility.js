document.querySelectorAll("[data-password-toggle]").forEach(button => {
  const password = document.getElementById(button.getAttribute("aria-controls"));
  if (!password) return;

  button.addEventListener("click", () => {
    const showPassword = password.type === "password";
    password.type = showPassword ? "text" : "password";
    button.setAttribute("aria-pressed", String(showPassword));
    button.setAttribute("aria-label", showPassword ? "Hide password" : "Show password");
    button.title = showPassword ? "Hide password" : "Show password";
  });
});
