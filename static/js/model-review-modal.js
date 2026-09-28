(function () {
  'use strict';

  function init(dialog) {
    if (dialog.dataset.reviewModalReady) return;
    var card = dialog.closest('.c3-model-card');
    var root = card && card.querySelector('[data-project-3d]');
    var expand = card && card.querySelector('[data-model-review-expand]');
    var host = dialog.querySelector('[data-model-review-dialog-body]');
    var close = dialog.querySelector('[data-model-review-close]');
    var treeToggle = dialog.querySelector('[data-model-review-tree-toggle]');
    if (!root || !expand || !host || !close) return;
    if (typeof dialog.showModal !== 'function') {
      expand.hidden = true;
      return;
    }
    dialog.dataset.reviewModalReady = 'true';

    var placeholder = null;
    var returnFocus = null;
    var previousOverflow = '';
    var previousPadding = '';
    var overflowPriority = '';
    var paddingPriority = '';

    function setTree(open) {
      dialog.classList.toggle('is-tree-open', open);
      if (treeToggle) treeToggle.setAttribute('aria-expanded', String(open));
    }

    function notifyLayout(expanded) {
      root.dataset.modelExpanded = String(expanded);
      var rect = root.getBoundingClientRect();
      root.dispatchEvent(new CustomEvent('model-review:visibility', {detail: {
        expanded: expanded,
        visible: expanded || (rect.bottom > 0 && rect.top < window.innerHeight)
      }}));
      window.requestAnimationFrame(function () {
        root.dispatchEvent(new CustomEvent('model-review:resize'));
        window.dispatchEvent(new Event('resize'));
      });
    }

    function restore() {
      if (!placeholder) return;
      // Moving the live root keeps its canvas, listeners, camera and selection.
      placeholder.replaceWith(root);
      placeholder = null;
      document.body.style.setProperty('overflow', previousOverflow, overflowPriority);
      document.body.style.setProperty('padding-right', previousPadding, paddingPriority);
      expand.setAttribute('aria-expanded', 'false');
      setTree(false);
      notifyLayout(false);
      var target = returnFocus && returnFocus.isConnected ? returnFocus : expand;
      target.focus({preventScroll: true});
      returnFocus = null;
    }

    function closeReview() {
      if (dialog.open) dialog.close();
      restore();
    }

    expand.addEventListener('click', function () {
      if (dialog.open || placeholder) return;
      returnFocus = document.activeElement;
      placeholder = document.createElement('div');
      placeholder.className = 'dx-review-placeholder';
      placeholder.style.height = root.getBoundingClientRect().height + 'px';
      placeholder.setAttribute('aria-hidden', 'true');
      root.before(placeholder);
      previousOverflow = document.body.style.getPropertyValue('overflow');
      previousPadding = document.body.style.getPropertyValue('padding-right');
      overflowPriority = document.body.style.getPropertyPriority('overflow');
      paddingPriority = document.body.style.getPropertyPriority('padding-right');
      var scrollbar = window.innerWidth - document.documentElement.clientWidth;
      if (scrollbar > 0) {
        var padding = parseFloat(window.getComputedStyle(document.body).paddingRight) || 0;
        document.body.style.setProperty('padding-right', (padding + scrollbar) + 'px');
      }
      document.body.style.setProperty('overflow', 'hidden');
      host.appendChild(root);
      try {
        dialog.showModal();
      } catch (error) {
        restore();
        return;
      }
      expand.setAttribute('aria-expanded', 'true');
      notifyLayout(true);
      close.focus({preventScroll: true});
    });

    close.addEventListener('click', closeReview);
    dialog.addEventListener('close', restore);
    dialog.addEventListener('cancel', function (event) {
      event.preventDefault();
      closeReview();
    });
    // Escape closes expanded review without clearing the current 3D selection.
    dialog.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      closeReview();
    }, true);
    if (treeToggle) treeToggle.addEventListener('click', function () {
      var open = !dialog.classList.contains('is-tree-open');
      setTree(open);
      if (open) {
        var query = root.querySelector('[data-project-query]');
        if (query) query.focus({preventScroll: true});
      }
    });
  }

  function mount() {
    document.querySelectorAll('[data-model-review-dialog]').forEach(init);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
  else mount();
  document.addEventListener('dashboard:panels-ready', mount);
}());
