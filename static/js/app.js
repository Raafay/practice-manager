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

// Folding panels remember, per browser, which ones the person closed.
const PANEL_PREFIX = "pm-panel-closed:";
function restorePanels(root) {
  root.querySelectorAll("details[data-panel]").forEach((panel) => {
    try {
      if (window.localStorage.getItem(PANEL_PREFIX + panel.dataset.panel) === "1") panel.open = false;
    } catch (error) {
      // Storage can be blocked; the panel just stays open.
    }
  });
}
document.addEventListener("DOMContentLoaded", () => restorePanels(document));
document.addEventListener("htmx:load", (event) => restorePanels(event.detail.elt));
document.addEventListener(
  "toggle",
  (event) => {
    const panel = event.target;
    if (!panel.matches || !panel.matches("details[data-panel]")) return;
    try {
      const key = PANEL_PREFIX + panel.dataset.panel;
      if (panel.open) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, "1");
    } catch (error) {
      // Ignore blocked storage.
    }
  },
  true,
);

// "/" jumps to the search box, unless the person is already typing somewhere.
document.addEventListener("keydown", (event) => {
  if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  if (target.closest && target.closest("input, textarea, select, [contenteditable=true]")) return;
  const box = document.getElementById("global-search");
  if (box) {
    event.preventDefault();
    box.focus();
  }
});

// Escape or a click elsewhere closes the search drop-down.
function closeSearch() {
  const results = document.getElementById("search-results");
  if (results) results.innerHTML = "";
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeSearch();
});
document.addEventListener("click", (event) => {
  if (!event.target.closest("[data-search]")) closeSearch();
});

// A select that applies itself when changed.
document.addEventListener("change", (event) => {
  if (event.target.matches("[data-submit-on-change]") && event.target.form) {
    event.target.form.requestSubmit();
  }
});

// Drag files onto the upload box.
document.addEventListener("dragover", (event) => {
  if (event.target.closest && event.target.closest("[data-dropzone-target]")) event.preventDefault();
});
document.addEventListener("drop", (event) => {
  const zone = event.target.closest && event.target.closest("[data-dropzone-target]");
  if (!zone) return;
  event.preventDefault();
  const form = zone.closest("form");
  const input = form && form.querySelector("input[type=file]");
  if (input && event.dataTransfer.files.length) {
    input.files = event.dataTransfer.files;
    form.requestSubmit();
  }
});

// "n" opens the New task drawer, unless the person is typing somewhere.
document.addEventListener("keydown", (event) => {
  if (event.key !== "n" || event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  if (target.closest && target.closest("input, textarea, select, trix-editor, [contenteditable=true], dialog[open]")) return;
  const link = document.getElementById("new-task-link");
  if (link) {
    event.preventDefault();
    link.click();
  }
});

// The header tick box ticks every row in its table.
document.addEventListener("change", (event) => {
  if (!event.target.matches("[data-check-all]")) return;
  const table = event.target.closest("table");
  table.querySelectorAll("tbody input[type=checkbox][name=ids]").forEach((box) => {
    box.checked = event.target.checked;
  });
});

// A page opened at a task's own address shows the task in the drawer over the list.
// Closing the drawer puts the list's address back.
function openDrawerOnLoad() {
  const drawer = document.getElementById("drawer");
  if (drawer && drawer.hasAttribute("data-open-on-load") && !drawer.open) {
    drawer.showModal();
    drawer.addEventListener("close", () => {
      const back = drawer.dataset.returnUrl;
      if (back) window.history.replaceState(null, "", back);
    });
  }
}
document.addEventListener("DOMContentLoaded", openDrawerOnLoad);

// Rich text takes no files: a paste or drop of a file into Trix is refused.
document.addEventListener("trix-file-accept", (event) => event.preventDefault());

// Click-to-insert merge fields: the field goes into the subject if that was the last
// box used, otherwise into the rich text editor on the same form.
let lastMergeBox = null;
document.addEventListener("focusin", (event) => {
  if (event.target.matches && event.target.matches("[data-merge-subject]")) lastMergeBox = event.target;
  else if (event.target.closest && event.target.closest("trix-editor")) lastMergeBox = null;
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-insert-field]");
  if (!button) return;
  event.preventDefault();
  const text = "{{ " + button.dataset.insertField + " }}";
  const form = button.closest("form");
  if (lastMergeBox && form && form.contains(lastMergeBox)) {
    const box = lastMergeBox;
    const start = box.selectionStart ?? box.value.length;
    box.value = box.value.slice(0, start) + text + box.value.slice(box.selectionEnd ?? start);
    box.focus();
    box.setSelectionRange(start + text.length, start + text.length);
    return;
  }
  const editor = form && form.querySelector("trix-editor");
  if (editor && editor.editor) {
    editor.focus();
    editor.editor.insertString(text);
  } else if (form) {
    const plain = form.querySelector("[data-merge-body]");
    if (plain) plain.value += text;
  }
});

// ---- Board and calendar: drag with SortableJS, save with fetch, put the card back on failure.

function showBoardMessage(text) {
  const box = document.getElementById("board-message");
  if (!box) return;
  box.textContent = text;
  box.classList.toggle("hidden", !text);
}

function putBack(item, from, index) {
  item.remove();
  from.insertBefore(item, from.children[index] || null);
}

async function saveMove(root, url, payload, item, from, oldIndex) {
  const body = new FormData();
  Object.entries(payload).forEach(([key, value]) => body.append(key, value));
  try {
    const response = await window.fetch(url, {
      method: "POST",
      body,
      headers: { "X-CSRFToken": root.dataset.csrf, "X-Requested-With": "fetch" },
      credentials: "same-origin",
    });
    if (!response.ok) {
      const text = response.status === 422 ? await response.text() : "";
      putBack(item, from, oldIndex);
      showBoardMessage(text || "That change could not be saved. The card was put back.");
      return false;
    }
    const html = await response.text();
    const holder = document.createElement("template");
    holder.innerHTML = html.trim();
    const fresh = holder.content.firstElementChild;
    if (fresh) {
      item.replaceWith(fresh);
      if (window.htmx) window.htmx.process(fresh);
    }
    showBoardMessage("");
    return true;
  } catch (error) {
    putBack(item, from, oldIndex);
    showBoardMessage("That change could not be saved. The card was put back.");
    return false;
  }
}

function recount(root) {
  root.querySelectorAll("[data-column-box]").forEach((box) => {
    const count = box.querySelector("[data-column-count]");
    const cards = box.querySelectorAll("[data-card]").length;
    if (count) count.textContent = String(cards);
  });
}

function initBoard(root) {
  if (!window.Sortable) return;
  root.querySelectorAll("[data-board]").forEach((board) => {
    if (board.dataset.sortableReady) return;
    board.dataset.sortableReady = "true";
    board.querySelectorAll("[data-column-cards]").forEach((list) => {
      window.Sortable.create(list, {
        group: "board",
        animation: 150,
        draggable: "[data-card]",
        ghostClass: "opacity-50",
        onEnd: async (event) => {
          if (event.from === event.to && event.oldIndex === event.newIndex) return;
          const item = event.item;
          const before = item.previousElementSibling;
          const after = item.nextElementSibling;
          const ok = await saveMove(
            board,
            board.dataset.moveUrl,
            {
              task: item.dataset.taskId,
              by: board.dataset.board,
              to: event.to.dataset.columnKey,
              before: before && before.dataset.taskId ? before.dataset.taskId : "",
              after: after && after.dataset.taskId ? after.dataset.taskId : "",
            },
            item,
            event.from,
            event.oldIndex,
          );
          if (ok !== undefined) recount(board);
        },
      });
    });
  });
}

function initCalendar(root) {
  if (!window.Sortable) return;
  root.querySelectorAll("[data-calendar]").forEach((calendar) => {
    if (calendar.dataset.sortableReady) return;
    calendar.dataset.sortableReady = "true";
    calendar.querySelectorAll("[data-day-tasks]").forEach((list) => {
      window.Sortable.create(list, {
        group: "calendar",
        animation: 150,
        draggable: "[data-calendar-task]",
        sort: false,
        disabled: list.hasAttribute("data-locked"),
        ghostClass: "opacity-50",
        onEnd: async (event) => {
          if (event.from === event.to) return;
          await saveMove(
            calendar,
            calendar.dataset.moveUrl,
            { task: event.item.dataset.taskId, date: event.to.dataset.date },
            event.item,
            event.from,
            event.oldIndex,
          );
          const empty = calendar.querySelector("[data-side-empty]");
          if (empty) empty.hidden = calendar.querySelector("aside [data-calendar-task]") !== null;
        },
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initBoard(document);
  initCalendar(document);
});
document.addEventListener("htmx:load", (event) => {
  initBoard(event.detail.elt);
  initCalendar(event.detail.elt);
});
