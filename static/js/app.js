// Small behaviours for the whole site. No inline scripts are allowed (strict CSP),
// so everything is wired here. Alpine components use the CSP build: each one is
// registered with Alpine.data and templates refer to it by name.

document.addEventListener("alpine:init", () => {
  // A menu that opens on click and closes on Escape or a click outside.
  window.Alpine.data("dropdown", () => ({
    open: false,
    toggle() {
      this.open = !this.open;
    },
    close() {
      this.open = false;
    },
  }));

  // A toast that hides itself. Errors stay until closed.
  window.Alpine.data("toast", () => ({
    shown: true,
    init() {
      if (this.$el.dataset.sticky !== "true") {
        setTimeout(() => {
          this.shown = false;
        }, 6000);
      }
    },
    dismiss() {
      this.shown = false;
    },
  }));
});

// Drawers and modals are <dialog> elements. HTMX loads their content, then they open.
document.addEventListener("htmx:afterSwap", (event) => {
  const dialog = event.detail.target.closest("dialog");
  if (dialog && !dialog.open) {
    dialog.showModal();
    const first = dialog.querySelector("[autofocus], input, select, textarea, button");
    if (first) first.focus();
  }
});

document.addEventListener("click", (event) => {
  const closer = event.target.closest("[data-dialog-close]");
  if (closer) {
    closer.closest("dialog").close();
    return;
  }
  // A click on the backdrop (the dialog element itself) closes it.
  if (event.target.tagName === "DIALOG") {
    event.target.close();
  }
});

// Buttons that open a dialog without loading anything.
document.addEventListener("click", (event) => {
  const opener = event.target.closest("[data-dialog-open]");
  if (opener) {
    const dialog = document.getElementById(opener.dataset.dialogOpen);
    if (dialog) dialog.showModal();
  }
});

// Forms that ask before doing something hard to undo.
document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

// Drag-to-reorder lists (SortableJS is loaded only on pages that use it).
function initSortable(root) {
  if (!window.Sortable) return;
  root.querySelectorAll("[data-sortable]").forEach((list) => {
    if (!list.dataset.sortableReady) {
      window.Sortable.create(list, { animation: 150, handle: "[data-sortable-handle]" });
      list.dataset.sortableReady = "true";
    }
  });
}
document.addEventListener("DOMContentLoaded", () => initSortable(document));
document.addEventListener("htmx:load", (event) => initSortable(event.detail.elt));
