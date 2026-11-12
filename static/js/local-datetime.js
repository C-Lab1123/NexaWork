(() => {
  document.addEventListener("submit", event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    form.querySelectorAll('input[type="datetime-local"][name]').forEach(input => {
      if (!input.value) return;
      const instant = new Date(input.value);
      if (Number.isNaN(instant.getTime())) return;

      const utcInput = document.createElement("input");
      utcInput.type = "hidden";
      utcInput.name = input.name;
      utcInput.value = instant.toISOString();
      input.removeAttribute("name");
      form.append(utcInput);
    });
  });
})();
