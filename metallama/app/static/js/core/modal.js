// Core modal dismissal helpers.
//
// Every overlay registers here so backdrop-click and Escape handling behave
// consistently. Two subtle issues motivated centralizing this:
//
//  1. `click` is dispatched on the nearest common ancestor of the pointerdown
//     and pointerup targets. The overlay *is* that ancestor for anything inside
//     the dialog, so a drag or a text selection that ends on the backdrop
//     produces a click whose target is the overlay. A naive "close when
//     event.target === overlay" handler treats that as a backdrop click and
//     destroys the modal mid-edit. We only honour the click when the press both
//     started and ended on the overlay itself.
//
//  2. Escape must only affect the front-most modal, must not fire when another
//     handler already consumed the key (`defaultPrevented`), and must not be
//     hijacked by a control that owns the key (e.g. an open <select> popup).

const registry = new Map(); // modal element -> close function
let escapeInstalled = false;

/** Return the front-most visible overlay, or null.
 *
 * Overlays all share a z-index and stack by DOM order, so the last visible one
 * in document order is on top.
 */
export function topmostOpenModal() {
  const visible = [...document.querySelectorAll(".modal-overlay:not(.is-hidden)")];
  return visible.length ? visible[visible.length - 1] : null;
}

/** True when `modal` is the currently front-most visible overlay. */
export function isTopmostModal(modal) {
  return topmostOpenModal() === modal;
}

/**
 * Wire up standard dismissal for an overlay: click on the backdrop and Escape
 * (when front-most). `close` is invoked when the modal should be closed.
 */
export function registerModal(modal, close) {
  if (!modal || typeof close !== "function" || registry.has(modal)) return;
  registry.set(modal, close);
  installBackdropDismiss(modal, close);
  installEscape();
}

function installBackdropDismiss(modal, close) {
  let pressStartedOnOverlay = false;

  modal.addEventListener("pointerdown", (event) => {
    // Only treat this as a backdrop press if it began directly on the overlay,
    // not on the dialog or one of its controls.
    pressStartedOnOverlay = event.target === modal;
  });

  modal.addEventListener("pointerup", (event) => {
    // Require the release to land on the overlay as well, so a drag that starts
    // on the backdrop but ends inside the dialog does not close it.
    if (event.target !== modal) pressStartedOnOverlay = false;
  });

  modal.addEventListener("click", (event) => {
    // A click whose target is the overlay can still be the synthetic common
    // ancestor of an unrelated drag/selection. Only close on a genuine
    // backdrop press-and-release.
    if (event.target === modal && pressStartedOnOverlay) {
      pressStartedOnOverlay = false;
      close();
    }
  });
}

function installEscape() {
  if (escapeInstalled) return;
  escapeInstalled = true;

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented) return;

    // An open native <select> popup owns Escape; let the browser dismiss it.
    if (event.target instanceof HTMLSelectElement) return;

    const modal = topmostOpenModal();
    if (!modal) return;
    const close = registry.get(modal);
    if (!close) return;

    event.preventDefault();
    // Claim the event so other document-level Escape listeners (e.g. the chat
    // conversation menu) don't act on the same keypress.
    event.stopImmediatePropagation();
    close();
  });
}
