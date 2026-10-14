// Keyboard shortcuts that need more than one key: "g" then a letter goes to a page, and
// "?" lists them all. "n" (new task) and "/" (search) are in app.js. Nothing here fires
// while someone is typing or while a window is open.
(function () {
  let waitingForSecondKey = false;
  let timer = null;

  function typing(target) {
    return Boolean(
      target.closest &&
        target.closest("input, textarea, select, trix-editor, [contenteditable=true], dialog[open]"),
    );
  }

  function reset() {
    waitingForSecondKey = false;
    clearTimeout(timer);
  }

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return;
    if (waitingForSecondKey) {
      const link = document.querySelector('a[data-go="' + event.key.toLowerCase() + '"]');
      reset();
      if (link) {
        event.preventDefault();
        link.click();
      }
      return;
    }
    if (event.key === "g") {
      waitingForSecondKey = true;
      timer = setTimeout(reset, 1500);
    } else if (event.key === "?") {
      const dialog = document.getElementById("shortcuts");
      if (dialog && !dialog.open) {
        event.preventDefault();
        dialog.showModal();
      }
    }
  });
})();
