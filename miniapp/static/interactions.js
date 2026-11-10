/* Visual-only busy state for controls disabled by an existing click handler.
 * Does not send requests, retry actions, intercept clicks or enable controls.
 */
(() => {
  'use strict';
  const busy = new WeakMap();
  let activated = null;
  let clearActivation;
  document.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    activated = button;
    clearTimeout(clearActivation);
    clearActivation = setTimeout(() => { activated = null; }, 0);
  }, true);
  const observer = new MutationObserver(records => {
    for (const {target: button} of records) {
      if (button.tagName !== 'BUTTON') continue;
      if (button.disabled && button === activated && !busy.has(button)) {
        busy.set(button, button.getAttribute('aria-busy'));
        button.classList.add('is-loading');
        button.setAttribute('aria-busy', 'true');
      } else if (!button.disabled && busy.has(button)) {
        const previous = busy.get(button);
        button.classList.remove('is-loading');
        if (previous === null) button.removeAttribute('aria-busy');
        else button.setAttribute('aria-busy', previous);
        busy.delete(button);
      }
    }
  });
  observer.observe(document.body, {subtree: true, attributes: true, attributeFilter: ['disabled']});
})();
