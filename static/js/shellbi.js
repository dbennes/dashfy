/* Shell BI - JS principal */
(function () {
  'use strict';

  const initLoginBoot = () => {
    const root = document.querySelector('[data-login-boot]');
    if (!root || root.dataset.loginBootStarted === '1') return;
    root.dataset.loginBootStarted = '1';

    const log = root.querySelector('[data-login-boot-log]');
    const bar = root.querySelector('[data-login-boot-bar]');
    const pct = root.querySelector('[data-login-boot-pct]');
    const engage = root.querySelector('[data-login-boot-engage]');
    const stats = {
      params: root.querySelector('[data-boot-stat="params"]'),
      ops: root.querySelector('[data-boot-stat="ops"]'),
      alerts: root.querySelector('[data-boot-stat="alerts"]'),
    };
    const modules = new Map(
      Array.from(root.querySelectorAll('[data-boot-module]'))
        .map(item => [item.dataset.bootModule, item])
    );
    const steps = [
      { time: '00:00.012', state: 'info', mark: '>', text: 'Mounting DASHFY operations kernel' },
      { time: '00:00.087', state: 'work', mark: '*', text: 'Opening encrypted session tunnel' },
      { time: '00:00.214', state: 'work', mark: '*', text: 'Connecting P6 schedule stream', module: 'p6' },
      { time: '00:00.441', state: 'ok', mark: 'OK', text: 'P6 schedule indexed', module: 'p6', done: true },
      { time: '00:00.593', state: 'work', mark: '*', text: 'Syncing DATAFY engineering and procurement', module: 'datafy' },
      { time: '00:00.842', state: 'ok', mark: 'OK', text: 'DATAFY cache available', module: 'datafy', done: true },
      { time: '00:01.016', state: 'work', mark: '*', text: 'Loading TASKFY action controls', module: 'taskfy' },
      { time: '00:01.247', state: 'ok', mark: 'OK', text: 'TASKFY work queues ready', module: 'taskfy', done: true },
      { time: '00:01.432', state: 'work', mark: '*', text: 'Calibrating AI cockpit assistant', module: 'ai' },
      { time: '00:01.684', state: 'ok', mark: 'OK', text: 'AI cockpit assistant online', module: 'ai', done: true },
      { time: '00:01.851', state: 'work', mark: '*', text: 'Preparing 3D viewer memory map', module: 'model' },
      { time: '00:02.071', state: 'ok', mark: 'OK', text: '3D model pipeline armed', module: 'model', done: true },
      { time: '00:02.251', state: 'info', mark: '>', text: 'Applying user permissions and admin gates' },
      { time: '00:02.438', state: 'ok', mark: 'OK', text: 'Construction cockpit ready' },
    ];
    let current = 0;
    let progress = 0;
    let finished = false;
    const timers = [];

    const setModule = (name, state) => {
      const item = modules.get(name);
      if (!item) return;
      const status = item.querySelector('.status');
      item.classList.toggle('is-working', state === 'work');
      item.classList.toggle('is-on', state === 'ok');
      if (status) status.textContent = state === 'ok' ? 'ONLINE' : 'BOOTING';
    };

    const appendLine = step => {
      if (!log) return;
      const line = document.createElement('div');
      line.className = `c3-boot-log-line ${step.state || 'info'}`;
      line.innerHTML = [
        `<span class="t">${step.time}</span>`,
        `<span class="s">${step.mark}</span>`,
        `<span class="msg">${step.text}</span>`,
      ].join('');
      log.appendChild(line);
      while (log.children.length > 8) log.firstElementChild.remove();
      log.scrollTop = log.scrollHeight;
    };

    const setProgress = value => {
      progress = Math.max(progress, Math.min(100, Math.round(value)));
      if (bar) bar.style.width = `${progress}%`;
      if (pct) pct.textContent = `${progress}%`;
    };

    const clearTimers = () => {
      timers.forEach(timer => clearTimeout(timer));
      timers.length = 0;
      if (root._bootStatsTimer) clearInterval(root._bootStatsTimer);
    };

    const finish = () => {
      if (finished) return;
      finished = true;
      clearTimers();
      Array.from(modules.keys()).forEach(name => setModule(name, 'ok'));
      setProgress(100);
      if (engage) engage.classList.add('is-visible');
      document.body.classList.remove('has-login-boot');
      document.body.classList.add('login-boot-ready');
      timers.push(setTimeout(() => {
        root.classList.add('is-fading');
        timers.push(setTimeout(() => root.remove(), 360));
      }, 260));
    };

    const tick = () => {
      if (finished) return;
      const step = steps[current];
      if (!step) {
        finish();
        return;
      }
      if (step.module) setModule(step.module, step.done ? 'ok' : 'work');
      appendLine(step);
      setProgress(((current + 1) / steps.length) * 100);
      current += 1;
      timers.push(setTimeout(tick, current < 4 ? 70 : 90));
    };

    root._bootStatsTimer = setInterval(() => {
      const seed = Date.now() / 700;
      if (stats.params) stats.params.textContent = String(1830 + Math.floor(Math.sin(seed) * 22 + 34));
      if (stats.ops) stats.ops.textContent = String(92 + Math.floor(Math.cos(seed) * 4 + 4));
      if (stats.alerts) stats.alerts.textContent = String(Math.max(0, 3 + Math.floor(Math.sin(seed * 1.7) * 2)));
    }, 160);

    root.addEventListener('click', finish);
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape' || event.key === 'Enter' || event.key === ' ') finish();
    });
    root.setAttribute('tabindex', '-1');
    root.focus({ preventScroll: true });
    tick();
  };

  initLoginBoot();

  const initConnectedFilters = () => {
    const form = document.querySelector('[data-c3-filterbar]');
    if (!form) return;

    const ensureField = (name, value = '') => {
      const directField = form.elements[name];
      let hidden = form.querySelector(`input[type="hidden"][data-c3-filter-hidden="${name}"]`);
      if (directField && directField.tagName === 'SELECT') {
        const hasOption = !value || Array.from(directField.options).some(option => option.value === value);
        directField.disabled = !hasOption;
        if (hasOption) {
          if (hidden) hidden.remove();
          return directField;
        }
        if (!hidden) {
          hidden = document.createElement('input');
          hidden.type = 'hidden';
          hidden.name = name;
          hidden.dataset.c3FilterHidden = name;
          form.appendChild(hidden);
        }
        return hidden;
      }
      if (directField) return directField;
      if (hidden) return hidden;
      let field = document.createElement('input');
      field.type = 'hidden';
      field.name = name;
      field.dataset.c3FilterHidden = name;
      form.appendChild(field);
      return field;
    };

    const submitFilters = anchor => {
      if (form.dataset.submitting === 'true') return;
      form.dataset.submitting = 'true';
      form.classList.add('is-applying');
      const targetAnchor = anchor || window.location.hash || '';
      form.action = `${window.location.pathname}${targetAnchor}`;
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
    };

    form.addEventListener('submit', () => {
      form.classList.add('is-applying');
      if (!form.getAttribute('action') && window.location.hash) {
        form.action = `${window.location.pathname}${window.location.hash}`;
      }
    });

    form.querySelectorAll('select, input[type="date"]').forEach(control => {
      control.addEventListener('change', () => submitFilters(window.location.hash));
    });

    document.addEventListener('click', event => {
      const trigger = event.target.closest('[data-c3-filter-set]');
      if (!trigger) return;
      event.preventDefault();
      event.stopPropagation();
      const name = trigger.dataset.c3FilterSet;
      const value = trigger.dataset.c3FilterValue || '';
      if (!name) return;
      const field = ensureField(name, value);
      field.value = field.value === value ? '' : value;
      submitFilters(trigger.dataset.c3FilterAnchor || window.location.hash);
    });
  };

  initConnectedFilters();

  const initMobileDisclosureControls = () => {
    const filterbar = document.querySelector('[data-c3-filterbar]');
    const filterToggle = filterbar ? filterbar.querySelector('[data-filterbar-toggle]') : null;
    if (filterbar && filterToggle) {
      filterbar.classList.add('is-mobile-filter-ready');
      const setFilterOpen = open => {
        filterbar.classList.toggle('is-mobile-expanded', open);
        filterToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      };
      setFilterOpen(false);
      filterToggle.addEventListener('click', () => {
        setFilterOpen(!filterbar.classList.contains('is-mobile-expanded'));
      });
    }

    document.querySelectorAll('[data-c3-grid-controls]').forEach(toolbar => {
      const toggle = toolbar.querySelector('[data-grid-mobile-toggle]');
      if (!toggle) return;
      toolbar.classList.add('is-mobile-tools-ready');
      const setToolsOpen = open => {
        toolbar.classList.toggle('is-mobile-tools-open', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      };
      setToolsOpen(false);
      toggle.addEventListener('click', () => {
        setToolsOpen(!toolbar.classList.contains('is-mobile-tools-open'));
      });
    });
  };

  initMobileDisclosureControls();

  // Sidebar toggle (mobile)
  const sidebar = document.getElementById('app-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  const toggle = document.getElementById('sidebar-toggle');
  const closeBtn = document.getElementById('sidebar-close');
  const setSidebar = (open) => {
    if (!sidebar) return;
    sidebar.classList.toggle('show', open);
    document.body.classList.toggle('sidebar-open', open);
  };
  if (toggle && sidebar) toggle.addEventListener('click', () => setSidebar(true));
  if (closeBtn && sidebar) closeBtn.addEventListener('click', () => setSidebar(false));
  if (backdrop) backdrop.addEventListener('click', () => setSidebar(false));

  // Theme toggle
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    const html = document.documentElement;
    const stored = localStorage.getItem('shellbi-theme');
    if (stored) html.setAttribute('data-bs-theme', stored);
    themeBtn.querySelector('i').className = html.getAttribute('data-bs-theme') === 'dark'
      ? 'bi bi-sun-fill'
      : 'bi bi-moon-stars-fill';
    themeBtn.addEventListener('click', () => {
      const cur = html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
      html.setAttribute('data-bs-theme', cur);
      localStorage.setItem('shellbi-theme', cur);
      themeBtn.querySelector('i').className = cur === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-stars-fill';
    });
  }

  // Init Select2 (multiselects automaticos)
  if (window.jQuery && jQuery.fn.select2) {
    jQuery('select.select2, select[multiple]').each(function () {
      jQuery(this).select2({ theme: 'bootstrap-5', width: '100%', placeholder: 'Select...' });
    });
  }

  // Flatpickr (date pickers)
  if (window.flatpickr) {
    document.querySelectorAll('input[type="date"], input.datepicker').forEach(el => {
      flatpickr(el, { dateFormat: 'Y-m-d', locale: 'pt', allowInput: true });
    });
    document.querySelectorAll('input.daterangepicker').forEach(el => {
      flatpickr(el, { mode: 'range', dateFormat: 'Y-m-d', locale: 'pt', allowInput: true });
    });
  }

  // DataTables (tabelas marcadas com .datatable)
  if (window.jQuery && jQuery.fn.DataTable) {
    jQuery('table.datatable').each(function () {
      jQuery(this).DataTable({
        pageLength: 25,
        lengthMenu: [10, 25, 50, 100, 250],
        language: {
          search: 'Search:',
          info: 'Showing _START_ to _END_ of _TOTAL_ records',
          infoEmpty: 'No records',
          infoFiltered: '(filtered from _MAX_)',
          lengthMenu: '_MENU_ per page',
          zeroRecords: 'No results found',
          paginate: { first: 'First', last: 'Last', next: 'Next', previous: 'Previous' },
        },
      });
    });
  }

  // Auto-submit filters on Enter
  document.querySelectorAll('#filters-bar input, #filters-bar select').forEach(el => {
    el.addEventListener('keydown', e => { if (e.key === 'Enter') el.form.submit(); });
  });
  document.querySelectorAll('.dx-column-filter, .dx-column-proxy-filter').forEach(el => {
    const submitColumnFilter = () => {
      if (!el.form) return;
      if (el.classList.contains('dx-column-proxy-filter')) {
        const targetName = el.getAttribute('data-target');
        const target = targetName ? el.form.querySelector(`input[name="${targetName}"]`) : null;
        if (target) target.value = el.value;
      }
      if (el.form.requestSubmit) el.form.requestSubmit();
      else el.form.submit();
    };
    if (el.tagName === 'SELECT') {
      el.addEventListener('change', submitColumnFilter);
    } else {
      el.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitColumnFilter();
        }
      });
    }
  });

  // Excel-like column filters for command/dashboard tables.
  const cleanCellText = value => String(value || '').replace(/\s+/g, ' ').trim();
  const normalizeCellText = value => cleanCellText(value)
    .toLocaleLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');
  const filterCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

  const allExcelFilterMenus = () => document.querySelectorAll('.dx-excel-filter-menu');
  const closeExcelFilterMenus = exceptMenu => {
    allExcelFilterMenus().forEach(menu => {
      if (menu === exceptMenu) return;
      menu.hidden = true;
      const th = menu.closest('th');
      if (th) th.classList.remove('is-filter-open');
      const btn = th ? th.querySelector('.dx-excel-filter-btn') : null;
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
  };

  const rowIsDataRow = row => {
    if (!row || row.hasAttribute('data-excel-empty-row')) return false;
    if (!row.cells.length) return false;
    return !(row.cells.length === 1 && row.cells[0].hasAttribute('colspan'));
  };

  const cellTextAt = (row, index) => {
    const cell = row && row.cells ? row.cells[index] : null;
    return cleanCellText(cell ? cell.textContent : '');
  };

  const visibleColumnCount = tableState => Math.max(1, tableState.headers.length);

  const rowMatchesExcelFilters = (row, tableState, exceptIndex = null) => {
    for (const [index, excludedValues] of tableState.filters.entries()) {
      if (index === exceptIndex || !excludedValues.size) continue;
      if (excludedValues.has(cellTextAt(row, index))) return false;
    }
    return true;
  };

  const updateExcelFilterSummaries = tableState => {
    tableState.headers.forEach((th, index) => {
      const btn = th.querySelector('.dx-excel-filter-btn');
      const excluded = tableState.filters.get(index);
      const isActive = !!(excluded && excluded.size);
      th.classList.toggle('has-excel-filter', isActive);
      if (btn) {
        btn.classList.toggle('is-active', isActive);
        btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
      }
    });
    tableState.table.classList.toggle('has-excel-filters', tableState.filters.size > 0);
  };

  const setExcelEmptyRow = (tableState, visibleRows) => {
    if (visibleRows > 0) {
      if (tableState.emptyRow && tableState.emptyRow.parentNode) {
        tableState.emptyRow.parentNode.removeChild(tableState.emptyRow);
      }
      return;
    }
    if (!tableState.emptyRow) {
      const row = document.createElement('tr');
      row.setAttribute('data-excel-empty-row', '');
      const cell = document.createElement('td');
      cell.className = 'empty-state dx-excel-empty-row';
      cell.textContent = 'No row matches the filters.';
      row.appendChild(cell);
      tableState.emptyRow = row;
    }
    tableState.emptyRow.firstElementChild.setAttribute('colspan', String(visibleColumnCount(tableState)));
    if (tableState.emptyRow.parentNode !== tableState.tbody) {
      tableState.tbody.appendChild(tableState.emptyRow);
    }
  };

  const applyExcelTableFilters = tableState => {
    let visibleRows = 0;
    tableState.rows.forEach(row => {
      const show = rowMatchesExcelFilters(row, tableState);
      row.hidden = !show;
      if (show) visibleRows += 1;
    });
    setExcelEmptyRow(tableState, visibleRows);
    updateExcelFilterSummaries(tableState);
  };

  const setColumnExcludedValues = (tableState, index, values) => {
    const nextValues = Array.from(values || []).map(value => cleanCellText(value));
    if (nextValues.length) tableState.filters.set(index, new Set(nextValues));
    else tableState.filters.delete(index);
  };

  const uniqueColumnValues = (tableState, index) => {
    const seen = new Set();
    const values = [];
    tableState.rows.forEach(row => {
      if (!rowMatchesExcelFilters(row, tableState, index)) return;
      const text = cellTextAt(row, index);
      if (seen.has(text)) return;
      seen.add(text);
      values.push(text);
    });
    return values.sort((a, b) => filterCollator.compare(a || '(vazio)', b || '(vazio)'));
  };

  const updateOptionSearch = (menu, searchInput) => {
    const needle = normalizeCellText(searchInput.value);
    let visible = 0;
    const options = Array.from(menu.querySelectorAll('[data-excel-filter-option]'));
    options.forEach(option => {
      const haystack = option.getAttribute('data-filter-search') || '';
      const show = !needle || haystack.includes(needle);
      option.hidden = !show;
      if (show) visible += 1;
    });
    const count = menu.querySelector('[data-excel-filter-count]');
    const empty = menu.querySelector('[data-excel-filter-empty]');
    if (count) count.textContent = `${visible} of ${options.length} options`;
    if (empty) empty.hidden = visible !== 0;
  };

  const renderExcelFilterMenu = (tableState, index, menu) => {
    const values = uniqueColumnValues(tableState, index);
    const excluded = tableState.filters.get(index) || new Set();
    const th = tableState.headers[index];
    const headerContent = th ? th.querySelector('.dx-excel-header-content') : null;
    const title = cleanCellText(headerContent ? headerContent.textContent : '');

    menu.innerHTML = '';

    const tools = document.createElement('div');
    tools.className = 'dx-excel-filter-tools';

    const search = document.createElement('input');
    search.type = 'search';
    search.placeholder = `Search in ${title || 'column'}`;
    search.setAttribute('aria-label', search.placeholder);

    const actions = document.createElement('div');
    actions.className = 'dx-excel-filter-actions';

    const selectAll = document.createElement('button');
    selectAll.type = 'button';
    selectAll.textContent = 'Todos';

    const deselectAll = document.createElement('button');
    deselectAll.type = 'button';
    deselectAll.textContent = 'None';

    const clear = document.createElement('button');
    clear.type = 'button';
    clear.textContent = 'Limpar';

    const apply = document.createElement('button');
    apply.type = 'button';
    apply.textContent = 'Aplicar';
    apply.className = 'dx-excel-filter-apply';

    actions.append(selectAll, deselectAll, clear, apply);
    tools.append(search, actions);
    menu.appendChild(tools);

    const count = document.createElement('div');
    count.className = 'dx-excel-filter-count';
    count.setAttribute('data-excel-filter-count', '');
    menu.appendChild(count);

    const list = document.createElement('div');
    list.className = 'dx-excel-filter-list';
    menu.appendChild(list);

    values.forEach(value => {
      const label = document.createElement('label');
      label.setAttribute('data-excel-filter-option', '');
      label.setAttribute('data-filter-search', normalizeCellText(value || '(vazio)'));

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = value;
      checkbox.checked = !excluded.has(value);

      const span = document.createElement('span');
      span.textContent = value || '(vazio)';
      span.title = value || '(vazio)';

      checkbox.addEventListener('change', () => {
        const currentExcluded = new Set(tableState.filters.get(index) || []);
        if (checkbox.checked) currentExcluded.delete(value);
        else currentExcluded.add(value);
        setColumnExcludedValues(tableState, index, currentExcluded);
        applyExcelTableFilters(tableState);
      });

      label.append(checkbox, span);
      list.appendChild(label);
    });

    const empty = document.createElement('div');
    empty.className = 'dx-excel-filter-empty';
    empty.setAttribute('data-excel-filter-empty', '');
    empty.hidden = true;
      empty.textContent = 'No options';
    menu.appendChild(empty);

    search.addEventListener('input', () => updateOptionSearch(menu, search));
    selectAll.addEventListener('click', () => {
      setColumnExcludedValues(tableState, index, []);
      applyExcelTableFilters(tableState);
      renderExcelFilterMenu(tableState, index, menu);
      search.focus();
    });
    deselectAll.addEventListener('click', () => {
      setColumnExcludedValues(tableState, index, values);
      applyExcelTableFilters(tableState);
      renderExcelFilterMenu(tableState, index, menu);
      search.focus();
    });
    clear.addEventListener('click', () => {
      setColumnExcludedValues(tableState, index, []);
      applyExcelTableFilters(tableState);
      menu.hidden = true;
      th.classList.remove('is-filter-open');
      const btn = th.querySelector('.dx-excel-filter-btn');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
    apply.addEventListener('click', () => {
      menu.hidden = true;
      th.classList.remove('is-filter-open');
      const btn = th.querySelector('.dx-excel-filter-btn');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });

    updateOptionSearch(menu, search);
  };

  const initExcelTableFilter = table => {
    if (!table || table.hasAttribute('data-excel-filters-ready')) return;
    const thead = table.tHead;
    const tbody = table.tBodies && table.tBodies[0];
    if (!thead || !tbody) return;

    const headerRow = thead.querySelector('.dx-column-header-row') || thead.rows[0];
    if (!headerRow) return;

    const headers = Array.from(headerRow.cells);
    const rows = Array.from(tbody.rows).filter(rowIsDataRow);
    if (!headers.length || !rows.length) return;

    table.setAttribute('data-excel-filters-ready', 'true');
    table.classList.add('dx-excel-filter-table');
    table.querySelectorAll('.dx-column-filter-row').forEach(row => {
      row.hidden = true;
      row.setAttribute('aria-hidden', 'true');
    });

    const tableState = {
      table,
      tbody,
      headers,
      rows,
      filters: new Map(),
      emptyRow: null,
    };
    table._dxExcelFilters = tableState;

    headers.forEach((th, index) => {
      th.classList.add('dx-excel-filter-th');

      const content = document.createElement('span');
      content.className = 'dx-excel-header-content';
      while (th.firstChild) content.appendChild(th.firstChild);
      th.appendChild(content);

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'dx-excel-filter-btn';
      button.title = 'Filtrar coluna';
      button.setAttribute('aria-label', 'Filtrar coluna');
      button.setAttribute('aria-expanded', 'false');
      button.innerHTML = '<i class="bi bi-funnel"></i>';

      const menu = document.createElement('div');
      menu.className = 'dx-excel-filter-menu';
      menu.hidden = true;
      menu.setAttribute('role', 'menu');
      if (index >= headers.length - 2) menu.classList.add('dx-excel-filter-menu-right');

      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        const willOpen = menu.hidden;
        closeExcelFilterMenus(menu);
        menu.hidden = !willOpen;
        th.classList.toggle('is-filter-open', willOpen);
        button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
        if (willOpen) {
          renderExcelFilterMenu(tableState, index, menu);
          window.setTimeout(() => {
            const input = menu.querySelector('input[type="search"]');
            if (input) input.focus();
          }, 0);
        }
      });

      menu.addEventListener('click', event => event.stopPropagation());
      th.append(button, menu);
    });

    applyExcelTableFilters(tableState);
  };

  document.querySelectorAll('table.dx-table-filtered').forEach(initExcelTableFilter);
  document.addEventListener('click', () => closeExcelFilterMenus());
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeExcelFilterMenus();
  });

  // P6-like outline/Gantt expansion.
  const escapeP6Html = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));

  const readP6Rows = schedule => {
    const scriptId = schedule.dataset.p6Rows;
    const script = scriptId ? document.getElementById(scriptId) : null;
    if (!script) return [];
    try {
      const rows = JSON.parse(script.textContent || '[]');
      return Array.isArray(rows) ? rows : [];
    } catch (error) {
      return [];
    }
  };

  const p6Field = (row, key, index) => Array.isArray(row) ? row[index] : row[key];

  const renderP6ScheduleRows = schedule => {
    if (schedule.querySelector('[data-p6-row]')) return;
    const grid = schedule.querySelector('.dx-p6-grid');
    if (!grid) return;
    const rows = readP6Rows(schedule);
    if (!Array.isArray(rows) || !rows.length) return;

    const html = rows.map(row => {
      const nodeId = p6Field(row, 'node_id', 0);
      const parentId = p6Field(row, 'parent_id', 1);
      const level = p6Field(row, 'level', 2);
      const displayId = p6Field(row, 'display_id', 3);
      const displayName = p6Field(row, 'display_name', 4);
      const startLabel = p6Field(row, 'start_label', 5);
      const finishLabel = p6Field(row, 'finish_label', 6);
      const pctComplete = p6Field(row, 'pct_complete', 7);
      const pctCss = p6Field(row, 'pct_complete_css', 8);
      const budget = p6Field(row, 'budget_nonlabor', 9);
      const actual = p6Field(row, 'actual_nonlabor', 10);
      const barLeft = p6Field(row, 'bar_left', 11);
      const barWidth = p6Field(row, 'bar_width', 12);
      const hasChildren = !!p6Field(row, 'has_children', 13);
      const initialExpanded = !!p6Field(row, 'initial_expanded', 14);
      const initialVisible = !!p6Field(row, 'initial_visible', 15);
      const hasBar = !!p6Field(row, 'has_bar', 16);
      const isMilestone = !!p6Field(row, 'is_milestone', 17);
      const isSummary = hasChildren;
      const hidden = initialVisible ? '' : ' hidden';
      const toggle = hasChildren
        ? `<button type="button" class="dx-p6-tree-toggle" aria-label="Expandir" aria-expanded="${initialExpanded ? 'true' : 'false'}"><i class="bi bi-caret-right-fill"></i></button>`
        : `<span class="dx-p6-tree-leaf ${isMilestone ? 'is-milestone' : ''}"></span>`;
      const bar = hasBar
        ? `<span class="dx-p6-bar ${isSummary ? 'is-summary' : ''} ${isMilestone ? 'is-milestone' : ''}" style="--left: ${escapeP6Html(barLeft)}%; --width: ${escapeP6Html(barWidth)}%; --progress: ${escapeP6Html(pctCss)}%;"><i></i></span>`
        : '';
      return `
        <div class="dx-p6-row ${isSummary ? 'is-summary' : ''}"
             data-p6-row
             data-node-id="${escapeP6Html(nodeId)}"
             data-parent-id="${escapeP6Html(parentId)}"
             data-p6-level="${escapeP6Html(level)}"
             data-has-children="${hasChildren ? 'true' : 'false'}"
             data-expanded="${initialExpanded ? 'true' : 'false'}"${hidden}>
          <div class="dx-p6-cell dx-p6-cell-toggle">${toggle}</div>
          <div class="dx-p6-cell dx-p6-cell-id dx-mono">${escapeP6Html(displayId || '-')}</div>
          <div class="dx-p6-cell dx-p6-cell-name" style="--p6-level: ${escapeP6Html(level)};">
            <span>${escapeP6Html(displayName || '-')}</span>
          </div>
          <div class="dx-p6-cell dx-p6-cell-date dx-mono">${escapeP6Html(startLabel || '-')}</div>
          <div class="dx-p6-cell dx-p6-cell-date dx-mono">${escapeP6Html(finishLabel || '-')}</div>
          <div class="dx-p6-cell dx-p6-cell-pct dx-mono">${escapeP6Html(pctComplete || '0.00%')}</div>
          <div class="dx-p6-cell dx-p6-cell-number dx-mono">${escapeP6Html(budget || '0')}</div>
          <div class="dx-p6-cell dx-p6-cell-number dx-mono">${escapeP6Html(actual || '0')}</div>
          <div class="dx-p6-cell dx-p6-cell-gantt"><div class="dx-p6-gantt-track">${bar}</div></div>
        </div>
      `;
    }).join('');
    grid.insertAdjacentHTML('beforeend', html);
  };

  const initP6DhtmlxSchedule = schedule => {
    const host = schedule.querySelector('[data-p6-dhtmlx]');
    if (!host || !window.gantt || host.dataset.ready === 'true') return false;

    const rows = readP6Rows(schedule);
    if (!rows.length) return false;

    const toIsoDate = label => {
      const text = String(label || '').trim();
      const match = text.match(/^(\d{2})\/(\d{2})\/(\d{2})$/);
      if (!match) return '';
      const year = Number(match[3]);
      const fullYear = year >= 70 ? 1900 + year : 2000 + year;
      return `${fullYear}-${match[2]}-${match[1]}`;
    };
    const clampProgress = value => Math.max(0, Math.min(1, Number(value || 0) / 100));
    const formatPercent = value => `${Math.round(Number(value || 0) * 10000) / 100}%`;
    const monthFormat = date => {
      const labels = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];
      return `${labels[date.getMonth()]}/${String(date.getFullYear()).slice(-2)}`;
    };

    const tasks = rows.map(row => {
      const startLabel = p6Field(row, 'start_label', 5);
      const finishLabel = p6Field(row, 'finish_label', 6);
      const pctCss = Number(p6Field(row, 'pct_complete_css', 8) || 0);
      const hasChildren = !!p6Field(row, 'has_children', 13);
      return {
        id: p6Field(row, 'node_id', 0),
        parent: p6Field(row, 'parent_id', 1) || 0,
        text: p6Field(row, 'display_name', 4) || '-',
        start_date: toIsoDate(startLabel),
        end_date: toIsoDate(finishLabel),
        progress: clampProgress(pctCss),
        open: !!p6Field(row, 'initial_expanded', 14),
        activity_id: p6Field(row, 'display_id', 3) || '-',
        start_label: startLabel || '-',
        finish_label: finishLabel || '-',
        pct_label: p6Field(row, 'pct_complete', 7) || '0.00%',
        budget: p6Field(row, 'budget_nonlabor', 9) || '0',
        actual: p6Field(row, 'actual_nonlabor', 10) || '0',
        level: Number(p6Field(row, 'level', 2) || 0),
        has_children: hasChildren,
        type: hasChildren ? window.gantt.config.types.project : window.gantt.config.types.task,
      };
    }).filter(task => task.id && task.start_date && task.end_date);

    if (!tasks.length) return false;

    try {
      window.gantt.plugins({ marker: true, tooltip: true, keyboard_navigation: true, fullscreen: true });
    } catch (error) {
      // Plugin availability varies by dhtmlx bundle; the core Gantt still renders.
    }

    window.gantt.clearAll();
    window.gantt.config.readonly = true;
    window.gantt.config.date_format = '%Y-%m-%d';
    window.gantt.config.duration_unit = 'day';
    window.gantt.config.row_height = 23;
    window.gantt.config.bar_height = 7;
    window.gantt.config.scale_height = 30;
    window.gantt.config.grid_width = 980;
    window.gantt.config.min_column_width = 48;
    window.gantt.config.show_grid = true;
    window.gantt.config.smart_rendering = true;
    window.gantt.config.smart_scales = true;
    window.gantt.config.static_background = true;
    window.gantt.config.columns = [
      { name: 'activity_id', label: 'ID', width: 92, resize: true, template: task => task.activity_id || '-' },
      { name: 'text', label: 'Task Name / WBS', tree: true, width: 390, resize: true },
      { name: 'start_label', label: 'Start', width: 72, align: 'center', resize: true, template: task => task.start_label || '-' },
      { name: 'finish_label', label: 'Finish', width: 72, align: 'center', resize: true, template: task => task.finish_label || '-' },
      { name: 'pct_label', label: '%', width: 56, align: 'right', resize: true, template: task => task.pct_label || '0.00%' },
      { name: 'budget', label: 'Budget', width: 78, align: 'right', resize: true, template: task => task.budget || '0' },
      { name: 'actual', label: 'Actual', width: 78, align: 'right', resize: true, template: task => task.actual || '0' },
    ];
    window.gantt.config.scales = [{ unit: 'month', step: 1, format: monthFormat }];
    window.gantt.templates.task_class = (start, end, task) => task.has_children ? 'dx-p6-dhtmlx-summary' : 'dx-p6-dhtmlx-task';
    window.gantt.templates.grid_row_class = (start, end, task) => task.has_children ? 'dx-p6-dhtmlx-summary-row' : '';
    window.gantt.templates.task_text = (start, end, task) => (task.progress || 0) >= 0.08 ? formatPercent(task.progress) : '';
    window.gantt.templates.tooltip_text = (start, end, task) => `
      <b>${escapeP6Html(task.activity_id || '-')}</b><br>
      ${escapeP6Html(task.text || '-')}<br>
      Start: ${escapeP6Html(task.start_label || '-')}<br>
      Finish: ${escapeP6Html(task.finish_label || '-')}<br>
      Progress: ${escapeP6Html(task.pct_label || '0.00%')}
    `;

    window.gantt.init(host);
    window.gantt.parse({ data: tasks });
    schedule.classList.add('is-dhtmlx-ready');
    host.dataset.ready = 'true';

    const firstTask = tasks.find(task => Number(task.level) <= 1) || tasks[0];
    if (firstTask?.start_date) window.gantt.showDate(new Date(`${firstTask.start_date}T00:00:00`));
    if (!window.gantt.$shellbiP6TodayMarker && window.gantt.addMarker) {
      window.gantt.$shellbiP6TodayMarker = window.gantt.addMarker({
        start_date: new Date(),
        css: 'dx-p6-today-marker',
        text: 'Today',
        title: 'Today',
      });
    }

    const setOutlineLevel = maxLevel => {
      window.gantt.eachTask(task => {
        task.open = !!task.has_children && Number(task.level || 0) < maxLevel;
      });
      window.gantt.render();
    };
    const card = schedule.closest('.dx-p6-board-card') || document;
    card.querySelectorAll('[data-p6-expand-all]').forEach(button => {
      button.addEventListener('click', () => {
        window.gantt.eachTask(task => { task.open = true; });
        window.gantt.render();
      });
    });
    card.querySelectorAll('[data-p6-collapse-all]').forEach(button => {
      button.addEventListener('click', () => {
        window.gantt.eachTask(task => { task.open = false; });
        window.gantt.render();
      });
    });
    card.querySelectorAll('[data-p6-show-levels]').forEach(button => {
      button.addEventListener('click', () => setOutlineLevel(Number(button.dataset.p6ShowLevels || 3)));
    });
    window.addEventListener('resize', () => window.gantt.setSizes());
    return true;
  };

  const initP6Schedule = schedule => {
    if (initP6DhtmlxSchedule(schedule)) return;
    renderP6ScheduleRows(schedule);
    const rows = Array.from(schedule.querySelectorAll('[data-p6-row]'));
    if (!rows.length) return;
    const byId = new Map(rows.map(row => [row.dataset.nodeId, row]));
    const hasChildren = row => row.dataset.hasChildren === 'true';
    const syncToggle = row => {
      const toggle = row.querySelector('.dx-p6-tree-toggle');
      if (!toggle) return;
      const expanded = row.dataset.expanded === 'true';
      toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    };
    const rowCanShow = row => {
      let parentId = row.dataset.parentId;
      while (parentId) {
        const parent = byId.get(parentId);
        if (!parent) return true;
        if (parent.dataset.expanded !== 'true') return false;
        parentId = parent.dataset.parentId;
      }
      return true;
    };
    const refreshRows = () => {
      rows.forEach(row => {
        row.hidden = !rowCanShow(row);
        syncToggle(row);
      });
    };
    const setOutlineLevel = maxLevel => {
      rows.forEach(row => {
        const level = Number(row.dataset.p6Level || 0);
        row.dataset.expanded = hasChildren(row) && level < maxLevel ? 'true' : 'false';
      });
      refreshRows();
    };

    schedule.addEventListener('click', event => {
      const toggle = event.target.closest('.dx-p6-tree-toggle');
      if (!toggle) return;
      const row = toggle.closest('[data-p6-row]');
      if (!row) return;
      row.dataset.expanded = row.dataset.expanded === 'true' ? 'false' : 'true';
      refreshRows();
      event.stopPropagation();
    });

    const card = schedule.closest('.dx-p6-board-card') || document;
    card.querySelectorAll('[data-p6-expand-all]').forEach(button => {
      button.addEventListener('click', () => {
        rows.forEach(row => { if (hasChildren(row)) row.dataset.expanded = 'true'; });
        refreshRows();
      });
    });
    card.querySelectorAll('[data-p6-collapse-all]').forEach(button => {
      button.addEventListener('click', () => {
        rows.forEach(row => { if (hasChildren(row)) row.dataset.expanded = 'false'; });
        refreshRows();
      });
    });
    card.querySelectorAll('[data-p6-show-levels]').forEach(button => {
      button.addEventListener('click', () => setOutlineLevel(Number(button.dataset.p6ShowLevels || 2)));
    });
    refreshRows();
  };

  document.querySelectorAll('[data-p6-schedule]').forEach(initP6Schedule);

  const initProjectConsult3D = root => {
    const treeScript = document.getElementById(root.dataset.treeScript || '');
    const wbsTree = treeScript ? JSON.parse(treeScript.textContent || '[]') : [];
    const queryInput = root.querySelector('[data-project-query]');
    const statusEl = root.querySelector('[data-project-status]');
    const selectionEl = root.querySelector('[data-project-selection]');
    const selectionCopyEl = root.querySelector('[data-project-selection-copy]');
    const wbsList = root.querySelector('[data-project-tree="wbs"]');
    const modelList = root.querySelector('[data-project-tree="model"]');
    const viewer = root.querySelector('[data-model-canvas]');
    const emptyState = root.querySelector('[data-model-empty]');
    const loadButton = root.querySelector('[data-model-load]');
    const fitButton = root.querySelector('[data-model-fit]');
    const clearButton = root.querySelector('[data-model-clear]');
    const isolateButton = root.querySelector('[data-model-isolate]');
    const tabs = Array.from(root.querySelectorAll('[data-project-tab]'));
    const normalize = value => String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const compactToken = value => normalize(value).replace(/[^a-z0-9]+/g, '');
    const selectColor = {
      hex: '#38bdf8',
      emissive: '#075985',
      three: 0x38bdf8,
    };
    const datafyColor = {
      hex: '#f9a8d4',
      emissive: '#831843',
      three: 0xf9a8d4,
    };
    const modelUrls = {
      overview: root.dataset.modelUrl || '',
      detail: root.dataset.modelDetailUrl || root.dataset.modelUrl || '',
      hierarchy: root.dataset.modelHierarchyUrl || '',
      selection: root.dataset.modelSelectionUrl || '',
      materialItems: root.dataset.materialItemsUrl || '',
    };
    const defaultTab = root.dataset.projectDefaultTab || (wbsList ? 'wbs' : 'model');
    const setLoadButton = (disabled, html) => {
      if (!loadButton) return;
      loadButton.disabled = !!disabled;
      if (html) loadButton.innerHTML = html;
    };
    const setModelControlsEnabled = enabled => {
      if (fitButton) fitButton.disabled = !enabled;
      if (clearButton) clearButton.disabled = !enabled;
    };
    const state = {
      activeTab: defaultTab,
      query: '',
      queryTokens: [],
      expanded: new Set(wbsTree.filter(node => Number(node.level || 0) < 2).map(node => node.id)),
      modelItems: [],
      hierarchyItems: [],
      hierarchyById: new Map(),
      hierarchyByParent: new Map(),
      hierarchyByName: new Map(),
      hierarchyByCompactName: new Map(),
      hierarchyExpanded: new Set(),
      hierarchyLoaded: false,
      hierarchyLoading: false,
      hierarchyPromise: null,
      hierarchySummary: null,
      selectedHierarchyId: '',
      supplyContext: null,
      datafyLineNode: null,
      datafyComponentNodes: [],
      datafyComponentTokens: [],
      datafyOverlay: null,
      datafyCallouts: null,
      datafyMaterialCollapsed: null,
      datafyRequestId: 0,
      isolateSelection: false,
      highlighted: [],
      selectionOverlay: null,
      selectionRequestId: 0,
      pointerDown: null,
      modelLoaded: false,
      modelRaycastMeshes: [],
      modelLoading: false,
      currentModelMode: '',
      animationStarted: false,
      autoRefineStarted: false,
      viewerVisible: false,
      pendingDetail: false,
      renderFrame: null,
      scene: null,
      camera: null,
      renderer: null,
      controls: null,
      loader: null,
      raycaster: null,
      model: null,
      THREE: null,
    };
    const byParent = new Map();
    const byId = new Map(wbsTree.map(node => [node.id, node]));
    wbsTree.forEach(node => {
      const parent = node.parent || '';
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(node);
    });
    const childrenOf = id => byParent.get(id || '') || [];
    const hasMatch = (node, query) => {
      if (!query) return true;
      const haystack = normalize(`${node.label} ${node.code} ${node.status_label}`);
      const own = state.queryTokens.length
        ? state.queryTokens.every(token => haystack.includes(token))
        : haystack.includes(query);
      if (own) return true;
      return childrenOf(node.id).some(child => hasMatch(child, query));
    };
    const setStatus = text => { if (statusEl) statusEl.textContent = text; };
    const clearDatafyFocus = () => {
      state.supplyContext = null;
      state.datafyLineNode = null;
      state.datafyComponentNodes = [];
      state.datafyComponentTokens = [];
      removeDatafyCallouts();
    };
    const selectedHierarchyNode = () => state.hierarchyById.get(state.selectedHierarchyId) || null;
    const datafyFocusNodeIds = () => {
      const ids = new Set();
      if (state.datafyLineNode?.id) ids.add(String(state.datafyLineNode.id));
      (state.datafyComponentNodes || []).forEach(node => {
        if (node?.id) ids.add(String(node.id));
      });
      return ids;
    };
    const nodeIsInDatafyFocus = node => !!node?.id && datafyFocusNodeIds().has(String(node.id));
    const datafyPickScopeNodes = () => {
      const output = [];
      const seen = new Set();
      const push = node => {
        if (!node?.id || seen.has(String(node.id))) return;
        seen.add(String(node.id));
        output.push(node);
      };
      push(state.datafyLineNode);
      (state.datafyComponentNodes || []).forEach(push);
      return output;
    };
    const updateIsolationControls = () => {
      const node = selectedHierarchyNode();
      const hasSelection = !!node;
      const canIsolate = state.modelLoaded && hasSelection && (!!node.bbox || !!state.selectionOverlay);
      if (isolateButton) {
        isolateButton.disabled = !canIsolate;
        isolateButton.classList.toggle('is-active', state.isolateSelection);
        isolateButton.setAttribute('aria-pressed', state.isolateSelection ? 'true' : 'false');
        const label = isolateButton.querySelector('[data-model-isolate-label]');
        if (label) label.textContent = state.isolateSelection ? 'Show all' : 'Isolate selection';
      }
      if (clearButton) clearButton.disabled = !(state.modelLoaded || hasSelection || state.isolateSelection);
    };
    const applyIsolationVisibility = (options = {}) => {
      if (state.model) state.model.visible = !state.isolateSelection;
      if (state.selectionOverlay) state.selectionOverlay.visible = true;
      root.classList.toggle('is-isolating-selection', state.isolateSelection);
      updateIsolationControls();
      if (options.render !== false) renderOnce();
    };
    const boxFromBbox = bbox => {
      if (!state.THREE || !Array.isArray(bbox) || bbox.length !== 6) return null;
      const [minX, minY, minZ, maxX, maxY, maxZ] = bbox;
      return new state.THREE.Box3(
        new state.THREE.Vector3(minX, minY, minZ),
        new state.THREE.Vector3(maxX, maxY, maxZ),
      );
    };
    const setIsolationMode = (active, options = {}) => {
      const node = selectedHierarchyNode();
      if (active && (!state.modelLoaded || !node || (!node.bbox && !state.selectionOverlay))) {
        setStatus('Select a structure with 3D volume before isolating it.');
        updateIsolationControls();
        return;
      }
      state.isolateSelection = !!active;
      applyIsolationVisibility({ render: false });
      if (state.isolateSelection) {
        const box = boxFromBbox(node?.bbox);
        if (box && options.frame !== false) frameBox(box, 1.55);
        setStatus(`Isolated selection: ${node.name}`);
      } else {
        if (state.model) state.model.visible = true;
        setStatus(state.modelLoaded ? 'Full 3D model visible.' : 'Selection isolation cleared.');
      }
      renderOnce();
    };
    const setSelection = node => {
      const target = selectionCopyEl || selectionEl;
      if (!target) return;
      const supplyContext = node?.supplyContext || state.supplyContext;
      const families = Array.isArray(supplyContext?.families) ? supplyContext.families.slice(0, 5) : [];
      const familyPills = families.map(family => `<b>${escapeP6Html(family)}</b>`).join('');
      const pendingText = Number(supplyContext?.pending || 0) > 0
        ? `${Number(supplyContext.pending).toLocaleString('pt-BR')} pending material`
        : '';
      const datafyHtml = supplyContext ? `
        <div class="dx-project-datafy-context ${pendingText ? 'has-pending' : ''}">
          <span>DATAFY</span>
          ${pendingText ? `<strong>${escapeP6Html(pendingText)}</strong>` : ''}
          ${familyPills ? `<em>${familyPills}</em>` : ''}
        </div>
      ` : '';
      target.innerHTML = `
        <span>Selection</span>
        <strong>${escapeP6Html(node?.label || node?.name || 'No item selected')}</strong>
        <small>${escapeP6Html(node?.code || node?.type || 'Use the 3D hierarchy or click the model for visual review.')} ${node?.finish ? `· Finish ${escapeP6Html(node.finish)}` : ''}</small>
        ${datafyHtml}
      `;
      updateIsolationControls();
    };
    const renderWbsBranch = (parentId, level, output) => {
      childrenOf(parentId).forEach(node => {
        if (!hasMatch(node, state.query)) return;
        const children = childrenOf(node.id);
        const isExpanded = state.expanded.has(node.id) || !!state.query;
        output.push(`
          <button type="button" class="dx-project-tree-item is-${escapeP6Html(node.status)}"
                  data-wbs-id="${escapeP6Html(node.id)}" style="--level:${level};">
            <span class="dx-project-tree-caret">${children.length ? (isExpanded ? 'v' : '>') : '-'}</span>
            <span class="dx-project-tree-text">
              <strong>${escapeP6Html(node.label)}</strong>
              <small>${escapeP6Html(node.code)} · ${escapeP6Html(node.pct)} · ${escapeP6Html(node.finish)}</small>
            </span>
            <em>${escapeP6Html(node.status_label)}</em>
          </button>
        `);
        if (children.length && isExpanded) renderWbsBranch(node.id, level + 1, output);
      });
    };
    const renderWbs = () => {
      if (!wbsList) return 0;
      const output = [];
      renderWbsBranch('', 0, output);
      wbsList.innerHTML = output.join('') || '<div class="dx-project-tree-empty">No WBS item found.</div>';
      return output.length;
    };
    const hierarchyChildrenOf = id => state.hierarchyByParent.get(id || '') || [];
    const renderHierarchyBranch = (parentId, output, cap) => {
      for (const node of hierarchyChildrenOf(parentId)) {
        if (output.length >= cap) return;
        const children = hierarchyChildrenOf(node.id);
        const isExpanded = state.hierarchyExpanded.has(node.id);
        const isSelected = state.selectedHierarchyId === node.id;
        output.push(`
          <button type="button" class="dx-project-tree-item ${node.mesh ? 'is-mesh' : ''} ${isSelected ? 'is-selected' : ''}"
                  data-model-node-id="${escapeP6Html(node.id)}" style="--level:${Math.min(node.depth, 8)};">
            <span class="dx-project-tree-caret">${children.length ? (isExpanded ? 'v' : '>') : '-'}</span>
            <span class="dx-project-tree-text">
              <strong>${escapeP6Html(node.name)}</strong>
              <small>Node ${escapeP6Html(node.id)} · level ${escapeP6Html(node.depth)} · ${node.children} children</small>
            </span>
            <em>${node.mesh ? 'Mesh' : 'Group'}</em>
          </button>
        `);
        if (children.length && isExpanded) renderHierarchyBranch(node.id, output, cap);
      }
    };
    const renderModelTree = () => {
      if (!modelList) return;
      if (state.hierarchyLoading) {
        modelList.innerHTML = '<div class="dx-project-tree-empty">Loading original GLB hierarchy...</div>';
        return;
      }
      if (!state.hierarchyLoaded) {
        modelList.innerHTML = '<div class="dx-project-tree-empty">Open this tab to load the original hierarchy from the 3D file.</div>';
        return;
      }
      const cap = 900;
      if (state.supplyContext && state.datafyLineNode) {
        const nodes = Array.isArray(state.datafyComponentNodes) ? state.datafyComponentNodes : [];
        const tokens = (state.datafyComponentTokens?.length ? state.datafyComponentTokens : state.supplyContext.tokens || [])
          .map(token => String(token || '').toUpperCase())
          .filter(Boolean);
        const families = Array.isArray(state.supplyContext.families) ? state.supplyContext.families.filter(Boolean) : [];
        const pending = Number(state.supplyContext.pending || 0);
        const familyText = families.length ? families.slice(0, 3).join(' / ') : (tokens.join(' / ') || 'pending material');
        const summaryLine = `
          <div class="dx-project-tree-summary is-datafy-focus">
            <strong>DATAFY focus</strong>
            <span>${pending ? `${pending.toLocaleString('pt-BR')} pending material · ` : ''}${nodes.length.toLocaleString('pt-BR')} component(s) marked</span>
            <small>${escapeP6Html(familyText)}</small>
          </div>
        `;
        const lineNode = state.datafyLineNode;
        const lineItem = `
          <button type="button" class="dx-project-tree-item is-datafy-line ${state.selectedHierarchyId === lineNode.id ? 'is-selected' : ''}"
                  data-model-node-id="${escapeP6Html(lineNode.id)}" style="--level:0;">
            <span class="dx-project-tree-caret">-</span>
            <span class="dx-project-tree-text">
              <strong>${escapeP6Html(lineNode.name)}</strong>
              <small>Line context · Node ${escapeP6Html(lineNode.id)}</small>
            </span>
            <em>Line</em>
          </button>
        `;
        const componentItems = nodes.map(item => {
          const upperName = String(item.name || '').toUpperCase();
          const badge = tokens.find(token => upperName.startsWith(`${token} `) || upperName.includes(` ${token} `)) || 'DATAFY';
          return `
            <button type="button" class="dx-project-tree-item is-mesh is-datafy-component ${state.selectedHierarchyId === item.id ? 'is-selected' : ''}"
                    data-model-node-id="${escapeP6Html(item.id)}" style="--level:1;">
              <span class="dx-project-tree-caret">-</span>
              <span class="dx-project-tree-text">
                <strong>${escapeP6Html(item.name)}</strong>
                <small>Node ${escapeP6Html(item.id)} · level ${escapeP6Html(item.depth)} · linked by ${escapeP6Html(badge)}</small>
              </span>
              <em>${escapeP6Html(badge)}</em>
            </button>
          `;
        }).join('');
        modelList.innerHTML = summaryLine + lineItem + (componentItems || '<div class="dx-project-tree-empty">No component-level DATAFY match found for this line.</div>');
        return;
      }
      if (state.query) {
        const matches = [];
        let totalMatches = 0;
        state.hierarchyItems.forEach(item => {
          const ok = state.queryTokens.length
            ? state.queryTokens.every(token => item.search.includes(token))
            : item.search.includes(state.query);
          if (!ok) return;
          totalMatches += 1;
          if (matches.length < cap) matches.push(item);
        });
        const summaryLine = `<div class="dx-project-tree-summary">${totalMatches.toLocaleString('pt-BR')} matches by name/tag/node ID · showing up to ${cap.toLocaleString('pt-BR')}</div>`;
        modelList.innerHTML = summaryLine + (matches.map(item => `
          <button type="button" class="dx-project-tree-item ${item.mesh ? 'is-mesh' : ''} ${state.selectedHierarchyId === item.id ? 'is-selected' : ''}"
                  data-model-node-id="${escapeP6Html(item.id)}" style="--level:${Math.min(item.depth, 8)};">
            <span class="dx-project-tree-caret">·</span>
            <span class="dx-project-tree-text">
              <strong>${escapeP6Html(item.name)}</strong>
              <small>Node ${escapeP6Html(item.id)} · level ${escapeP6Html(item.depth)} · ${item.children} children</small>
            </span>
            <em>${item.mesh ? 'Mesh' : 'Group'}</em>
          </button>
        `).join('') || '<div class="dx-project-tree-empty">No original hierarchy item found.</div>');
        return;
      }
      const output = [];
      renderHierarchyBranch('', output, cap);
      const summary = state.hierarchySummary;
      const summaryLine = summary
          ? `<div class="dx-project-tree-summary">${Number(summary.nodes || 0).toLocaleString('pt-BR')} original nodes · ${Number(summary.mesh_nodes || 0).toLocaleString('pt-BR')} meshes · ${Number(summary.bbox_nodes || 0).toLocaleString('pt-BR')} selectable · showing up to ${cap.toLocaleString('pt-BR')}</div>`
        : '';
      modelList.innerHTML = summaryLine + (output.join('') || '<div class="dx-project-tree-empty">Original hierarchy is empty.</div>');
    };
    const loadHierarchy = async () => {
      if (state.hierarchyLoaded) return state.hierarchyItems;
      if (!modelUrls.hierarchy) return [];
      if (state.hierarchyPromise) return state.hierarchyPromise;
      state.hierarchyLoading = true;
      renderModelTree();
      state.hierarchyPromise = (async () => {
        try {
          const response = await fetch(modelUrls.hierarchy, { cache: 'force-cache' });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const payload = await response.json();
          const items = (payload.nodes || []).map(row => ({
            id: String(row[0]),
            parent: Number(row[1]) >= 0 ? String(row[1]) : '',
            depth: Number(row[2]) || 0,
            name: String(row[3] || `Node ${row[0]}`),
            mesh: Number(row[4]) === 1,
            children: Number(row[5]) || 0,
            bbox: Array.isArray(row[6]) && row[6].length === 6 ? row[6].map(Number) : null,
          }));
          const byParentHierarchy = new Map();
          const byIdHierarchy = new Map();
          const byNameHierarchy = new Map();
          const byCompactNameHierarchy = new Map();
          const expanded = new Set();
          const pushIndex = (map, key, item) => {
            if (!key) return;
            if (!map.has(key)) map.set(key, []);
            map.get(key).push(item);
          };
          items.forEach(item => {
            const parentPath = item.name.split('/').filter(Boolean).join(' ');
            item.search = normalize(`${item.name} ${parentPath} ${item.id} node ${item.id} ${item.mesh ? 'mesh' : 'group'}`);
            item.compactSearch = compactToken(`${item.name} ${parentPath}`);
            byIdHierarchy.set(item.id, item);
            pushIndex(byNameHierarchy, item.name, item);
            pushIndex(byCompactNameHierarchy, compactToken(item.name), item);
            if (!byParentHierarchy.has(item.parent)) byParentHierarchy.set(item.parent, []);
            byParentHierarchy.get(item.parent).push(item);
            if (item.children && item.depth < 3) expanded.add(item.id);
          });
          state.hierarchyItems = items;
          state.hierarchyById = byIdHierarchy;
          state.hierarchyByParent = byParentHierarchy;
          state.hierarchyByName = byNameHierarchy;
          state.hierarchyByCompactName = byCompactNameHierarchy;
          state.hierarchyExpanded = expanded;
          state.hierarchySummary = payload.summary || null;
          state.hierarchyLoaded = true;
          const total = state.hierarchySummary?.nodes || items.length;
          setStatus(`Original hierarchy loaded: ${total.toLocaleString('pt-BR')} nodes.`);
          if (state.modelLoaded && state.model) indexModel(state.model);
          return items;
        } catch (error) {
          setStatus(`Failed to load original hierarchy: ${error?.message || 'unknown error'}`);
          return [];
        } finally {
          state.hierarchyLoading = false;
          state.hierarchyPromise = null;
          renderModelTree();
        }
      })();
      return state.hierarchyPromise;
    };
    const setActiveTab = tab => {
      if (tab === 'wbs' && !wbsList) tab = 'model';
      state.activeTab = tab;
      tabs.forEach(button => button.classList.toggle('is-active', button.dataset.projectTab === tab));
      wbsList?.classList.toggle('is-active', tab === 'wbs');
      modelList?.classList.toggle('is-active', tab === 'model');
      if (tab === 'model') loadHierarchy();
    };
    const resetHighlights = () => {
      state.highlighted.forEach(item => { item.mesh.material = item.material; });
      state.highlighted = [];
      if (state.datafyOverlay) {
        state.scene?.remove(state.datafyOverlay);
        state.datafyOverlay.traverse?.(child => {
          child.geometry?.dispose?.();
          const materials = Array.isArray(child.material) ? child.material : [child.material];
          materials.forEach(material => material?.dispose?.());
        });
        state.datafyOverlay = null;
      }
      if (state.selectionOverlay) {
        state.scene?.remove(state.selectionOverlay);
        state.selectionOverlay.traverse?.(child => {
          child.geometry?.dispose?.();
          const materials = Array.isArray(child.material) ? child.material : [child.material];
          materials.forEach(material => material?.dispose?.());
        });
        state.selectionOverlay = null;
      }
    };
    const createHighlightMaterial = material => {
      const tint = source => {
        if (!source?.clone) return source;
        const clone = source.clone();
        if (clone.color) clone.color.set(selectColor.hex);
        if (clone.emissive) clone.emissive.set(selectColor.emissive);
        return clone;
      };
      return Array.isArray(material) ? material.map(tint) : tint(material);
    };
    const createOpaqueSelectionMaterial = (material, palette = selectColor, options = {}) => {
      const weak = !!options.weak;
      const overlay = !!options.overlay;
      const tint = source => {
        const solid = source?.clone
          ? source.clone()
          : new state.THREE.MeshStandardMaterial({
            roughness: 0.72,
            metalness: 0.04,
          });
        if (solid.color) solid.color.set(palette.three);
        if (solid.emissive) {
          solid.emissive.set(palette.emissive);
          solid.emissiveIntensity = weak ? 0.08 : 0.18;
        }
        solid.transparent = weak;
        solid.opacity = weak ? 0.5 : 1;
        solid.alphaMap = null;
        solid.alphaTest = 0;
        solid.depthWrite = !weak;
        solid.depthTest = true;
        solid.side = overlay ? state.THREE.FrontSide : state.THREE.DoubleSide;
        solid.polygonOffset = overlay;
        solid.polygonOffsetFactor = overlay ? -4 : 0;
        solid.polygonOffsetUnits = overlay ? -4 : 0;
        solid.needsUpdate = true;
        return solid;
      };
      return Array.isArray(material) ? material.map(tint) : tint(material);
    };
    const highlightObjects = objects => {
      if (!state.THREE || !state.modelLoaded) return;
      resetHighlights();
      let count = 0;
      objects.some(object => {
        object.traverse?.(child => {
          if (count >= 80 || !child.isMesh || !child.material) return;
          state.highlighted.push({ mesh: child, material: child.material });
          child.material = createHighlightMaterial(child.material);
          count += 1;
        });
        return count >= 80;
      });
      if (count) setStatus(`${count} objects highlighted in 3D.`);
    };
    const highlightByTerms = node => {
      if (!state.modelLoaded) return;
      if (state.modelItems.length <= 3 && state.model) {
        highlightObjects([state.model]);
        setStatus('Management focus applied to the model. To search real objects by tag, use a tiles/metadata conversion.');
        return;
      }
      const code = String(node.code || '').replace('-', '').trim();
      const terms = code && code.length > 2
        ? [normalize(code)]
        : normalize(node.label || '').split(/[^a-z0-9]+/).filter(term => term.length > 3).slice(0, 4);
      if (!terms.length) return;
      const matches = state.modelItems.filter(item => terms.some(term => normalize(item.name).includes(term))).slice(0, 60);
      highlightObjects(matches.map(item => item.object));
      if (!matches.length) setStatus('WBS item selected. No equivalent name was found in the 3D model.');
    };
    const getFrameBox = () => {
      if (!state.model || !state.THREE) return null;
      const fullBox = new state.THREE.Box3().setFromObject(state.model);
      const meshes = [];
      let vertexCount = 0;
      state.model.updateWorldMatrix(true, true);
      state.model.traverse(child => {
        const position = child.geometry?.attributes?.position;
        if (!child.isMesh || !position) return;
        meshes.push({ mesh: child, position });
        vertexCount += position.count;
      });
      if (!meshes.length || vertexCount < 2000) return fullBox;
      const targetSamples = 18000;
      const stride = Math.max(1, Math.floor(vertexCount / targetSamples));
      const coords = { x: [], y: [], z: [] };
      const point = new state.THREE.Vector3();
      meshes.forEach(({ mesh, position }) => {
        for (let i = 0; i < position.count; i += stride) {
          point.fromBufferAttribute(position, i).applyMatrix4(mesh.matrixWorld);
          coords.x.push(point.x);
          coords.y.push(point.y);
          coords.z.push(point.z);
        }
      });
      if (coords.x.length < 100) return fullBox;
      const pick = (values, pct) => {
        values.sort((a, b) => a - b);
        return values[Math.min(values.length - 1, Math.max(0, Math.floor(values.length * pct)))];
      };
      const robustBox = new state.THREE.Box3(
        new state.THREE.Vector3(pick(coords.x, 0.02), pick(coords.y, 0.02), pick(coords.z, 0.02)),
        new state.THREE.Vector3(pick(coords.x, 0.98), pick(coords.y, 0.98), pick(coords.z, 0.98)),
      );
      const robustSize = robustBox.getSize(new state.THREE.Vector3());
      return Math.max(robustSize.x, robustSize.y, robustSize.z) > 0 ? robustBox : fullBox;
    };
    const frameBox = (box, margin = 1.15) => {
      if (!box || !state.THREE || !state.camera || !state.controls) return;
      const size = box.getSize(new state.THREE.Vector3());
      const center = box.getCenter(new state.THREE.Vector3());
      const maxSize = Math.max(size.x, size.y, size.z) || 10;
      const fitDistance = maxSize / (2 * Math.tan((Math.PI * state.camera.fov) / 360));
      const distance = Math.max(fitDistance / Math.max(state.camera.aspect, 0.2), fitDistance) * margin;
      state.camera.position.set(center.x + distance, center.y + distance * 0.55, center.z + distance);
      state.camera.near = Math.max(distance / 1000, 0.01);
      state.camera.far = Math.max(distance * 12, maxSize * 20, 1000);
      state.camera.updateProjectionMatrix();
      state.controls.target.copy(center);
      state.controls.maxDistance = Math.max(distance * 8, maxSize * 4);
      state.controls.update();
    };
    const frameModel = () => {
      if (!state.model || !state.THREE || !state.camera || !state.controls) return;
      const box = getFrameBox();
      if (!box) return;
      frameBox(box, 0.66);
    };
    const highlightHierarchyNode = node => {
      if (!state.THREE || !state.scene || !node?.bbox) {
        setStatus('Item has no selectable 3D volume in metadata.');
        return;
      }
      resetHighlights();
      const [minX, minY, minZ, maxX, maxY, maxZ] = node.bbox;
      const box = new state.THREE.Box3(
        new state.THREE.Vector3(minX, minY, minZ),
        new state.THREE.Vector3(maxX, maxY, maxZ),
      );
      const size = box.getSize(new state.THREE.Vector3());
      const center = box.getCenter(new state.THREE.Vector3());
      const maxSize = Math.max(size.x, size.y, size.z);
      if (!Number.isFinite(maxSize) || maxSize <= 0) {
        setStatus('Selected item has no valid 3D dimension.');
        return;
      }
      const minThickness = Math.max(maxSize * 0.025, 0.12);
      const visibleSize = new state.THREE.Vector3(
        Math.max(size.x, minThickness),
        Math.max(size.y, minThickness),
        Math.max(size.z, minThickness),
      );
      const overlay = new state.THREE.Group();
      const fill = new state.THREE.Mesh(
        new state.THREE.BoxGeometry(visibleSize.x, visibleSize.y, visibleSize.z),
        new state.THREE.MeshBasicMaterial({
          color: selectColor.three,
          transparent: false,
          opacity: 1,
          wireframe: true,
          depthWrite: false,
        }),
      );
      fill.userData.hierarchyNodeId = node.id;
      fill.position.copy(center);
      overlay.add(fill);
      const helper = new state.THREE.Box3Helper(box, selectColor.three);
      helper.userData.hierarchyNodeId = node.id;
      overlay.add(helper);
      state.scene.add(overlay);
      state.selectionOverlay = overlay;
      applyIsolationVisibility({ render: false });
      frameBox(box, 1.55);
      renderOnce();
      setStatus(state.isolateSelection ? `Isolated selection: ${node.name}` : `Selected and highlighted: ${node.name}`);
    };
    const selectionUrlFor = node => {
      if (!modelUrls.selection || !node?.id) return '';
      return modelUrls.selection.replace(/0\.glb(?=($|\?))/, `${encodeURIComponent(node.id)}.glb`);
    };
    const loadSelectionGeometry = async (node, options = {}) => {
      const url = selectionUrlFor(node);
      if (!url || !state.loader || !state.THREE) return false;
      const requestId = state.selectionRequestId + 1;
      state.selectionRequestId = requestId;
      try {
        const response = await fetch(url, { cache: 'force-cache' });
        if (!response.ok) {
          if (response.status === 413) {
            setStatus(`Large group highlighted by volume: ${node.name}`);
            return false;
          }
          throw new Error(`HTTP ${response.status}`);
        }
        const buffer = await response.arrayBuffer();
        const gltf = await new Promise((resolve, reject) => {
          state.loader.parse(buffer, '', resolve, reject);
        });
        if (requestId !== state.selectionRequestId) {
          disposeObject(gltf.scene);
          return false;
        }
        resetHighlights();
        const palette = options.palette || selectColor;
        gltf.scene.userData.hierarchyNodeId = node.id;
        gltf.scene.traverse(child => {
          if (!child.isMesh) return;
          child.userData.hierarchyNodeId = node.id;
          child.material = createOpaqueSelectionMaterial(child.material, palette, { weak: options.weak });
          child.renderOrder = 2;
        });
        state.scene.add(gltf.scene);
        state.selectionOverlay = gltf.scene;
        applyIsolationVisibility({ render: false });
        if (node.bbox) {
          const [minX, minY, minZ, maxX, maxY, maxZ] = node.bbox;
          frameBox(new state.THREE.Box3(
            new state.THREE.Vector3(minX, minY, minZ),
            new state.THREE.Vector3(maxX, maxY, maxZ),
          ), 1.55);
        }
        renderOnce();
        if (options.status !== false) {
          setStatus(state.isolateSelection ? `Isolated exact surface: ${node.name}` : `Exact surface highlighted: ${node.name}`);
        }
        return true;
      } catch (error) {
        if (options.status !== false) {
          setStatus(`Volume highlighted; exact surface unavailable: ${error?.message || 'unknown error'}`);
        }
        return false;
      }
    };
    const datafyItemNumber = (item, fields, fallback = 0) => {
      const fieldList = Array.isArray(fields) ? fields : [fields];
      for (const field of fieldList) {
        const value = Number(item?.[field]);
        if (Number.isFinite(value)) return value;
      }
      return fallback;
    };
    const inferSupplyTokensFromText = value => {
      const text = normalize(value);
      const tokens = new Set();
      const supportLike = /support|suport|shoe|guide|trunnion|trunion|trunn|repad|base plate|attachment/.test(text);
      const flangoletLike = /flangolet|flgol/.test(text);
      if (/\bvalve\b/.test(text)) tokens.add('VALVE');
      if (/\bgasket\b|junta/.test(text)) tokens.add('GASKET');
      if (/stud\s*bolt|\bbolt\b|\bnut\b|parafuso|porca/.test(text)) {
        tokens.add('BOLT');
        tokens.add('GENSEC');
      }
      if (/\bolet\b|weldolet|sockolet/.test(text) || flangoletLike) {
        tokens.add('OLET');
        tokens.add('FLANGE');
      } else if (/\bflange\b|flanged|blind flange/.test(text)) {
        tokens.add('FLANGE');
      }
      if (/\belbow\b/.test(text)) tokens.add('ELBOW');
      if (/\bbend\b/.test(text)) tokens.add('BEND');
      if (/\btee\b/.test(text)) tokens.add('TEE');
      if (/\bcap\b/.test(text)) tokens.add('CAP');
      if (supportLike) {
        tokens.add('ATTACHMENT');
        tokens.add('PCOMPONENT');
        tokens.add('TRUNNION');
      }
      if (!supportLike && /\bpipe\b|\btube\b/.test(text)) tokens.add('TUBE');
      return Array.from(tokens);
    };
    const supplyItemTokens = item => {
      const explicit = Array.isArray(item?.match_tokens)
        ? item.match_tokens.map(token => String(token || '').toUpperCase().trim()).filter(Boolean)
        : [];
      if (explicit.length) return Array.from(new Set(explicit));
      return inferSupplyTokensFromText([
        item?.family,
        item?.code,
        item?.cpmtocode,
        item?.description,
      ].join(' '));
    };
    const supplyItemIsSupportLike = item => {
      if (item?.attention) return true;
      const text = normalize([
        item?.family,
        item?.code,
        item?.cpmtocode,
        item?.description,
        item?.attention_label,
      ].join(' '));
      return /pipe support|special support|support|suport|shoe|guide|trunnion|trunion|trunn|line stop|repad|base plate|attachment|welded pipe shoes/.test(text);
    };
    const supplyItemCanCreateVisualReference = item => {
      if (!item || supplyItemIsSupportLike(item)) return false;
      const tokens = supplyItemTokens(item);
      if (tokens.length === 1 && tokens[0] === 'TUBE') return false;
      return true;
    };
    const supplyComponentTokens = context => {
      const items = Array.isArray(context?.items) ? context.items : [];
      const missingItems = items.filter(item => datafyItemNumber(item, ['missing_qty', 'missing']) > 0 && !item.attention);
      if (items.length) {
        const tokens = new Set();
        missingItems
          .filter(supplyItemCanCreateVisualReference)
          .forEach(item => supplyItemTokens(item).forEach(token => tokens.add(token)));
        return Array.from(tokens);
      }
      if (context?.requiresDatafyLookup || context?.materialLookupLoaded) return [];
      return inferSupplyTokensFromText([
        ...(Array.isArray(context?.families) ? context.families : []),
        context?.code,
        context?.description,
      ].join(' '));
    };
    const loadDatafyMaterialItems = async context => {
      if (!modelUrls.materialItems || !context) return null;
      const params = new URLSearchParams(window.location.search || '');
      params.set('drawing', context.drawing || '');
      params.set('line', context.line || '');
      params.set('scope', context.scope || '');
      params.set('status', 'all');
      const url = `${modelUrls.materialItems}?${params.toString()}`;
      const response = await fetch(url, {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`DATAFY material lookup ${response.status}`);
      return response.json();
    };
    const hierarchyDescendantsOf = (rootId, cap = 5000) => {
      const output = [];
      const stack = [...hierarchyChildrenOf(rootId)].reverse();
      while (stack.length && output.length < cap) {
        const node = stack.pop();
        if (!node) continue;
        output.push(node);
        const children = hierarchyChildrenOf(node.id);
        for (let index = children.length - 1; index >= 0; index -= 1) {
          stack.push(children[index]);
        }
      }
      return output;
    };
    const nodeMatchesLine = (node, candidates) => {
      const compactName = compactToken(node?.name || '');
      return candidates.some(candidate => compactName.includes(compactToken(candidate)));
    };
    const nodeBelongsToExactLinePath = (node, candidates) => {
      const compactName = compactToken(node?.name || '');
      return candidates.some(candidate => {
        const compact = compactToken(candidate);
        if (!compact) return false;
        return compactName === compact
          || compactName.startsWith(compact)
          || compactName.includes(`branch${compact}`)
          || compactName.includes(`line${compact}`);
      });
    };
    const nodeComponentMatchScore = (node, tokens) => {
      const name = String(node?.name || '').toUpperCase();
      let bestScore = Number.POSITIVE_INFINITY;
      tokens.forEach((rawToken, index) => {
        const token = String(rawToken || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
        if (!token) return;
        const base = index * 12;
        let score = Number.POSITIVE_INFINITY;
        if (name.startsWith(`${token} `)) score = base;
        else if (name.includes(` ${token} `)) score = base + 4;
        else if (name.includes(`${token} `) && name.indexOf(token) <= 3) score = base + 8;
        if (Number.isFinite(score)) {
          score += Math.max(0, Number(node?.depth || 0) - 6) * 0.03;
          score += Math.log10(bboxVolume(node?.bbox) + 1) * 0.0003;
          bestScore = Math.min(bestScore, score);
        }
      });
      return bestScore;
    };
    const nodeMatchesComponent = (node, tokens) => {
      return Number.isFinite(nodeComponentMatchScore(node, tokens));
    };
    const visualLimitForDatafyItem = item => {
      const qty = Math.ceil(Math.max(1, datafyItemNumber(item, ['missing_qty', 'missing'], 1)));
      const tokens = supplyItemTokens(item);
      if (tokens.includes('BOLT') || tokens.includes('GENSEC')) return 1;
      return Math.min(qty, 4);
    };
    const findSupplyComponentNodes = (candidates, context, rootNode = null) => {
      const tokens = supplyComponentTokens(context);
      if (!tokens.length) return { tokens, nodes: [] };
      const source = rootNode?.id
        ? [rootNode, ...hierarchyDescendantsOf(rootNode.id)]
        : state.hierarchyItems;
      const lineNodes = source.filter(item => (
        item.mesh
        && item.bbox
        && (rootNode?.id ? nodeBelongsToExactLinePath(item, candidates) : nodeMatchesLine(item, candidates))
      ));
      const missingItems = Array.isArray(context?.items)
        ? context.items.filter(item => (
          datafyItemNumber(item, ['missing_qty', 'missing']) > 0
          && supplyItemCanCreateVisualReference(item)
        ))
        : [];
      if (context?.requiresDatafyLookup && !missingItems.length) {
        return { tokens, nodes: [] };
      }
      if (missingItems.length) {
        const nodes = [];
        const usedIds = new Set();
        missingItems.forEach(item => {
          const itemTokens = supplyItemTokens(item);
          if (!itemTokens.length) return;
          const ranked = lineNodes
            .filter(node => !usedIds.has(String(node.id || '')))
            .map(node => ({ node, score: nodeComponentMatchScore(node, itemTokens) }))
            .filter(hit => Number.isFinite(hit.score))
            .sort((a, b) => a.score - b.score);
          const limit = visualLimitForDatafyItem(item);
          ranked.slice(0, limit).forEach(hit => {
            usedIds.add(String(hit.node.id || ''));
            nodes.push({
              ...hit.node,
              materialItem: item,
              materialTokens: itemTokens,
            });
          });
        });
        return { tokens, nodes: nodes.slice(0, 16) };
      }
      const nodes = lineNodes
        .filter(item => nodeMatchesComponent(item, tokens))
        .slice(0, 16);
      return { tokens, nodes };
    };
    const removeDatafyOverlay = () => {
      if (!state.datafyOverlay) return;
      state.scene?.remove(state.datafyOverlay);
      state.datafyOverlay.traverse?.(child => {
        child.geometry?.dispose?.();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach(material => material?.dispose?.());
      });
      state.datafyOverlay = null;
    };
    const removeDatafyCallouts = () => {
      state.datafyCallouts?.root?.remove?.();
      state.datafyCallouts = null;
    };
    const formatDatafyQty = value => {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) return '0';
      return number.toLocaleString('pt-BR', { maximumFractionDigits: number % 1 ? 2 : 0 });
    };
    const formatDatafyDate = value => {
      const text = String(value || '').trim();
      if (!text) return '';
      const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (match) return `${match[3]}/${match[2]}/${match[1]}`;
      return text;
    };
    const compactDatafyList = (values, emptyLabel = '--', limit = 2) => {
      const clean = values
        .map(value => String(value || '').trim())
        .filter(Boolean);
      if (!clean.length) return emptyLabel;
      const visible = clean.slice(0, limit).join(', ');
      return clean.length > limit ? `${visible} +${clean.length - limit}` : visible;
    };
    const datafyPoValues = item => {
      const values = [];
      if (Array.isArray(item?.po_delivery_pairs)) {
        item.po_delivery_pairs.forEach(pair => {
          if (pair?.po) values.push(pair.po);
        });
      }
      if (Array.isArray(item?.po_list)) values.push(...item.po_list);
      if (item?.po) values.push(...String(item.po).split(/[,;]+/));
      const seen = new Set();
      return values
        .map(value => String(value || '').trim())
        .filter(value => value && !/^no linked po$/i.test(value) && value !== '-')
        .filter(value => {
          const key = value.toUpperCase();
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
    };
    const datafyEtaValues = item => {
      const values = [];
      if (Array.isArray(item?.po_delivery_pairs)) {
        item.po_delivery_pairs.forEach(pair => {
          if (pair?.expected_date) values.push(pair.expected_date);
        });
      }
      if (Array.isArray(item?.po_expected_dates)) values.push(...item.po_expected_dates);
      if (item?.po_expected_date || item?.eta || item?.expected_date) {
        values.push(item.po_expected_date || item.eta || item.expected_date);
      }
      const seen = new Set();
      return values
        .map(formatDatafyDate)
        .filter(Boolean)
        .filter(value => {
          const key = value.toUpperCase();
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
    };
    const datafyMaterialLabel = value => {
      const text = String(value || '').trim();
      const aliases = {
        ATTACHMENT: 'Attachment',
        PCOMPONENT: 'Component',
        TRUNNION: 'Trunnion',
        TUBE: 'Pipe / tube',
        FLANGE: 'Flange',
        GASKET: 'Gasket',
        VALVE: 'Valve',
        ELBOW: 'Elbow',
        BEND: 'Bend',
        TEE: 'Tee',
        OLET: 'Olet',
        CAP: 'Cap',
        BOLT: 'Bolt / nut',
        GENSEC: 'Bolt / nut',
      };
      const upper = text.toUpperCase();
      return aliases[upper] || text.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').slice(0, 46);
    };
    const cleanDatafyFamily = value => {
      const text = String(value || '').trim();
      if (!text || text === '-') return '';
      const normalized = normalize(text);
      if (/pipe support|shoe|guide|support/.test(normalized)) return '';
      return text;
    };
    const datafyRowFromMaterialItem = item => {
      const missing = datafyItemNumber(item, ['missing_qty', 'missing']);
      const allocated = datafyItemNumber(item, ['allocated_qty', 'allocated']);
      const stock = datafyItemNumber(item, ['stock_free_qty', 'stock']);
      const requested = datafyItemNumber(item, ['requested_qty', 'requested']);
      const unit = item?.unit || '';
      const kind = item?.attention ? 'attention' : missing > 0 ? (allocated > 0 || stock > 0 ? 'partial' : 'missing') : 'available';
      const qty = missing > 0
        ? `${formatDatafyQty(missing)} ${unit}`.trim()
        : `${formatDatafyQty(allocated || stock || requested || 1)} ${unit}`.trim();
      const code = item?.code || item?.cpmtocode || '';
      const family = cleanDatafyFamily(item?.family);
      const poValues = datafyPoValues(item);
      const etaValues = datafyEtaValues(item);
      const detail = [
        code,
        item?.size,
        family,
        item?.scope_label || item?.scope,
      ].filter(Boolean).join(' · ');
      const status = item?.attention
        ? 'Support/trunnion note'
        : kind === 'partial'
          ? 'Partial'
          : kind === 'missing'
            ? 'Missing'
            : 'Available';
      const attentionDetail = item?.attention_label || 'Support/trunnion only; not counted as missing material';
      return {
        kind,
        label: item?.description || code || datafyMaterialLabel(family) || 'DATAFY material',
        detail: item?.attention ? `${attentionDetail}${detail ? ` · ${detail}` : ''}` : detail || item?.status_label || item?.status || 'DATAFY row',
        status,
        po: compactDatafyList(poValues),
        poFull: poValues.join(', '),
        eta: compactDatafyList(etaValues),
        etaFull: etaValues.join(', '),
        qty: item?.attention ? 'note' : qty,
      };
    };
    const buildDatafyMaterialRows = (lineNode, componentNodes, componentTokens = []) => {
      const context = state.supplyContext || {};
      const rows = [];
      const items = Array.isArray(context.items) ? context.items : [];
      items.forEach(item => {
        rows.push(datafyRowFromMaterialItem(item));
      });
      if (items.length) {
        const rowRank = { missing: 0, partial: 1, available: 2, attention: 3, info: 4 };
        rows.sort((a, b) => (rowRank[a.kind] ?? 9) - (rowRank[b.kind] ?? 9));
      }
      const covered = Number(context.covered || 0);
      const pending = Number(context.pending || 0);
      const total = Number(context.total || 0);
      const families = Array.isArray(context.families) ? context.families.filter(Boolean) : [];
      if (!rows.length && (total || covered || pending)) {
        rows.push({
          kind: 'available',
          label: 'Available material',
          detail: total ? `${formatDatafyQty(covered)} of ${formatDatafyQty(total)} items` : 'Covered items',
          qty: formatDatafyQty(covered),
        });
        if (families.length && pending > 0) {
          families.slice(0, 5).forEach(family => {
            rows.push({
              kind: 'missing',
              label: datafyMaterialLabel(family),
              detail: 'Missing in DATAFY',
              qty: 'pending',
            });
          });
        } else {
          rows.push({
            kind: pending > 0 ? 'missing' : 'available',
            label: 'Missing material',
            detail: 'Pending items',
            qty: formatDatafyQty(pending),
          });
        }
        if (Number(context.withPo || 0)) {
          rows.push({
            kind: 'info',
            label: 'With PO',
            detail: 'Purchase order linked',
            qty: formatDatafyQty(context.withPo),
          });
        }
        if (Number(context.poNotArrived || 0)) {
          rows.push({
            kind: 'partial',
            label: 'PO not at yard',
            detail: 'Ordered, not received',
            qty: formatDatafyQty(context.poNotArrived),
          });
        }
      }
      if (!rows.length && families.length) {
        families.slice(0, 5).forEach(family => {
          rows.push({
            kind: 'missing',
            label: datafyMaterialLabel(family),
            detail: 'Missing in DATAFY',
            qty: pending ? formatDatafyQty(pending) : 'check',
          });
        });
      }
      if (!items.length) componentTokens.slice(0, Math.max(0, 7 - rows.length)).forEach(token => {
        if (rows.some(row => row.label.toUpperCase() === datafyMaterialLabel(token).toUpperCase())) return;
        rows.push({
          kind: 'missing',
          label: datafyMaterialLabel(token),
          detail: '3D match from DATAFY family',
          qty: 'marked',
        });
      });
      if (!rows.length) {
        rows.push({
          kind: 'info',
          label: 'DATAFY selection',
          detail: 'No material detail available',
          qty: 'check',
        });
      }
      const limit = 18;
      if (rows.length <= limit) return rows;
      const byKind = kind => rows.filter(row => row.kind === kind);
      const missingRows = byKind('missing');
      const partialRows = byKind('partial');
      const availableRows = byKind('available');
      const attentionRows = byKind('attention');
      const infoRows = byKind('info');
      const fixedRows = [...missingRows, ...partialRows, ...attentionRows, ...infoRows];
      const availableLimit = Math.max(0, limit - fixedRows.length);
      if (!missingRows.length && !partialRows.length) {
        return [
          ...availableRows.slice(0, Math.max(0, limit - attentionRows.length - infoRows.length)),
          ...attentionRows,
          ...infoRows,
        ].slice(0, limit);
      }
      return [
        ...missingRows,
        ...partialRows,
        ...availableRows.slice(0, availableLimit),
        ...attentionRows,
        ...infoRows,
      ].slice(0, limit);
    };
    const createDatafyCallouts = (lineNode, componentNodes, componentTokens = []) => {
      if (!viewer || !state.THREE || !state.camera || !Array.isArray(componentNodes)) return;
      removeDatafyCallouts();
      const rows = buildDatafyMaterialRows(lineNode, componentNodes, componentTokens);
      if (!componentNodes.length && !rows.length) return;
      const rootEl = document.createElement('div');
      rootEl.className = 'dx-project-callouts';
      rootEl.setAttribute('data-project-callouts', '');
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'dx-project-callout-svg');
      svg.setAttribute('aria-hidden', 'true');
      const labelRows = rows.filter(row => ['missing', 'partial'].includes(row.kind));
      const calloutRows = labelRows;
      const labels = document.createElement('div');
      labels.className = 'dx-project-callout-labels';
      const markerNodes = calloutRows.length
        ? componentNodes
          .filter(node => supplyItemCanCreateVisualReference(node.materialItem))
          .slice(0, Math.min(6, calloutRows.length))
        : [];
      const markers = markerNodes.map((node, index) => {
        const row = node.materialItem ? datafyRowFromMaterialItem(node.materialItem) : calloutRows[index % calloutRows.length];
        if (row.kind === 'attention') return null;
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('class', 'dx-project-callout-line');
        const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot.setAttribute('class', 'dx-project-callout-dot');
        dot.setAttribute('r', '3.5');
        const label = document.createElement('div');
        label.className = `dx-project-callout-label is-${row.kind}`;
        label.innerHTML = `
          <strong>${escapeP6Html(row.label)}</strong>
          <small>${escapeP6Html(row.qty)} · ${escapeP6Html(row.detail)}</small>
        `;
        svg.append(line, dot);
        labels.appendChild(label);
        return { node, index, row, line, dot, label };
      }).filter(Boolean);
      const missingCount = Number(state.supplyContext?.pending || 0) || rows.filter(row => row.kind === 'missing').length;
      const attentionCount = Number(state.supplyContext?.attentionCount || 0) || rows.filter(row => row.kind === 'attention').length;
      const rowsHtml = rows.map((row, index) => `
        <div class="dx-project-material-row is-${escapeP6Html(row.kind)}" data-callout-row="${index}"
             title="${escapeP6Html([row.label, row.detail, row.poFull || row.po, row.etaFull || row.eta].filter(Boolean).join(' | '))}">
          <span class="dx-project-material-state"></span>
          <strong title="${escapeP6Html(row.label)}">${escapeP6Html(row.label)}</strong>
          <small title="${escapeP6Html(row.detail)}">${escapeP6Html(row.status || row.detail || '-')}</small>
          <em title="${escapeP6Html(row.poFull || row.po || '')}">${escapeP6Html(row.po || '--')}</em>
          <time title="${escapeP6Html(row.etaFull || row.eta || '')}">${escapeP6Html(row.eta || '--')}</time>
          <b>${escapeP6Html(row.qty)}</b>
        </div>
      `).join('');
      const materialNote = missingCount <= 0
        ? `<div class="dx-project-material-note is-ok">
            ${attentionCount
              ? 'No missing main material in DATAFY. Support/trunnion remains as an observation only.'
              : 'No missing main material in DATAFY for this line.'}
          </div>`
        : '';
      const mobileMaterialPanel = window.matchMedia?.('(max-width: 700px)').matches;
      const panelCollapsed = mobileMaterialPanel && state.datafyMaterialCollapsed !== false;
      const toggleLabel = panelCollapsed ? 'Show list' : 'Hide list';
      const toggleIcon = panelCollapsed ? 'bi-chevron-down' : 'bi-chevron-up';
      const panel = document.createElement('div');
      panel.className = `dx-project-material-panel${panelCollapsed ? ' is-collapsed' : ''}`;
      panel.innerHTML = `
        <div class="dx-project-material-head">
          <div class="dx-project-material-title">
            <span>Material check</span>
            <strong>${escapeP6Html(state.supplyContext?.drawing || lineNode?.name || 'Selected line')}</strong>
            <small>${escapeP6Html(state.supplyContext?.line || lineNode?.name || '')}</small>
          </div>
          <button type="button" class="dx-project-material-toggle" data-material-panel-toggle aria-expanded="${panelCollapsed ? 'false' : 'true'}">
            <i class="bi ${toggleIcon}" aria-hidden="true"></i>
            <span>${toggleLabel}</span>
          </button>
        </div>
        ${materialNote}
        <div class="dx-project-material-table">
          <div class="dx-project-material-row is-header">
            <span></span><strong>Material</strong><small>Status</small><em>PO</em><time>Delivery</time><b>Qty</b>
          </div>
          ${rowsHtml}
        </div>
      `;
      rootEl.append(svg, labels, panel);
      viewer.appendChild(rootEl);
      const toggle = panel.querySelector('[data-material-panel-toggle]');
      const syncToggle = () => {
        const collapsed = panel.classList.contains('is-collapsed');
        toggle?.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        const icon = toggle?.querySelector('i');
        const label = toggle?.querySelector('span');
        if (icon) icon.className = `bi ${collapsed ? 'bi-chevron-down' : 'bi-chevron-up'}`;
        if (label) label.textContent = collapsed ? 'Show list' : 'Hide list';
      };
      toggle?.addEventListener('click', () => {
        const collapsed = !panel.classList.contains('is-collapsed');
        panel.classList.toggle('is-collapsed', collapsed);
        state.datafyMaterialCollapsed = collapsed;
        syncToggle();
        updateDatafyCallouts();
      });
      state.datafyCallouts = { root: rootEl, svg, panel, labels, markers };
      updateDatafyCallouts();
    };
    const updateDatafyCallouts = () => {
      const callouts = state.datafyCallouts;
      if (!callouts || !state.camera || !state.THREE || !viewer) return;
      const width = Math.max(viewer.clientWidth, 1);
      const height = Math.max(viewer.clientHeight, 1);
      callouts.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const midX = width * 0.5;
      callouts.markers.forEach(marker => {
        const box = boxFromBbox(marker.node.bbox);
        if (!box || !marker.label) {
          marker.line.style.display = 'none';
          marker.dot.style.display = 'none';
          marker.label.style.display = 'none';
          return;
        }
        const center = box.getCenter(new state.THREE.Vector3()).project(state.camera);
        if (!Number.isFinite(center.x) || !Number.isFinite(center.y) || center.z < -1 || center.z > 1) {
          marker.line.style.display = 'none';
          marker.dot.style.display = 'none';
          marker.label.style.display = 'none';
          return;
        }
        const sourceX = (center.x * 0.5 + 0.5) * width;
        const sourceY = (-center.y * 0.5 + 0.5) * height;
        const side = sourceX < midX ? -1 : 1;
        const labelWidth = Math.min(176, Math.max(112, width * 0.14));
        const offsetX = (side < 0 ? 136 : 120) + (marker.index % 2) * 34;
        const stagger = [-76, -28, 34, 84, -116, 122];
        const offsetY = stagger[marker.index % stagger.length];
        const rawTargetX = side < 0 ? sourceX - offsetX - labelWidth : sourceX + offsetX;
        const targetX = Math.min(width - labelWidth - 14, Math.max(14, rawTargetX));
        const targetY = Math.min(height - 58, Math.max(18, sourceY + offsetY));
        const lineEndX = side < 0 ? targetX + labelWidth : targetX;
        const lineEndY = targetY + 15;
        marker.label.style.display = '';
        marker.label.style.width = `${labelWidth}px`;
        marker.label.style.transform = `translate(${targetX.toFixed(1)}px, ${targetY.toFixed(1)}px)`;
        marker.line.style.display = '';
        marker.dot.style.display = '';
        marker.line.setAttribute('x1', sourceX.toFixed(1));
        marker.line.setAttribute('y1', sourceY.toFixed(1));
        marker.line.setAttribute('x2', lineEndX.toFixed(1));
        marker.line.setAttribute('y2', lineEndY.toFixed(1));
        marker.dot.setAttribute('cx', sourceX.toFixed(1));
        marker.dot.setAttribute('cy', sourceY.toFixed(1));
      });
    };
    const createDatafyBoxOverlay = nodes => {
      if (!state.THREE || !state.scene || !nodes.length) return null;
      removeDatafyOverlay();
      const group = new state.THREE.Group();
      nodes.forEach(node => {
        const box = boxFromBbox(node.bbox);
        if (!box) return;
        const size = box.getSize(new state.THREE.Vector3());
        const center = box.getCenter(new state.THREE.Vector3());
        const maxSize = Math.max(size.x, size.y, size.z);
        const minThickness = Math.max(maxSize * 0.03, 0.08);
        const visibleSize = new state.THREE.Vector3(
          Math.max(size.x, minThickness),
          Math.max(size.y, minThickness),
          Math.max(size.z, minThickness),
        );
        const fill = new state.THREE.Mesh(
          new state.THREE.BoxGeometry(visibleSize.x, visibleSize.y, visibleSize.z),
          new state.THREE.MeshBasicMaterial({
            color: datafyColor.three,
            transparent: false,
            opacity: 1,
            depthWrite: true,
            depthTest: true,
            side: state.THREE.FrontSide,
            polygonOffset: true,
            polygonOffsetFactor: -4,
            polygonOffsetUnits: -4,
          }),
        );
        fill.userData.hierarchyNodeId = node.id;
        fill.position.copy(center);
        fill.renderOrder = 8;
        const helper = new state.THREE.Box3Helper(box, datafyColor.three);
        helper.userData.hierarchyNodeId = node.id;
        group.add(fill);
        group.add(helper);
      });
      if (!group.children.length) return null;
      state.scene.add(group);
      state.datafyOverlay = group;
      renderOnce();
      return group;
    };
    const loadDatafyComponentGeometry = async nodes => {
      if (!nodes.length || !state.loader || !state.THREE) return false;
      const requestId = state.datafyRequestId + 1;
      state.datafyRequestId = requestId;
      const group = new state.THREE.Group();
      const targets = nodes.slice(0, 16);
      for (const node of targets) {
        const url = selectionUrlFor(node);
        if (!url) continue;
        try {
          const response = await fetch(url, { cache: 'force-cache' });
          if (!response.ok) continue;
          const buffer = await response.arrayBuffer();
          const gltf = await new Promise((resolve, reject) => {
            state.loader.parse(buffer, '', resolve, reject);
          });
          if (requestId !== state.datafyRequestId) return false;
          gltf.scene.userData.hierarchyNodeId = node.id;
          gltf.scene.traverse(child => {
            if (!child.isMesh) return;
            child.userData.hierarchyNodeId = node.id;
            child.material = createOpaqueSelectionMaterial(child.material, datafyColor, { overlay: true });
            const materials = Array.isArray(child.material) ? child.material : [child.material];
            materials.forEach(material => {
              material.depthTest = true;
              material.depthWrite = true;
              material.side = state.THREE.FrontSide;
              material.polygonOffset = true;
              material.polygonOffsetFactor = -4;
              material.polygonOffsetUnits = -4;
              material.needsUpdate = true;
            });
            child.renderOrder = 9;
          });
          group.add(gltf.scene);
        } catch (error) {
          // Keep the bounding boxes when exact component geometry is unavailable.
        }
      }
      if (requestId !== state.datafyRequestId || !group.children.length) return false;
      removeDatafyOverlay();
      state.scene.add(group);
      state.datafyOverlay = group;
      renderOnce();
      return true;
    };
    const renderDatafyFocusOverlays = (lineNode, componentNodes, componentTokens = [], matchTerm = '') => {
      if (!state.modelLoaded || !lineNode?.bbox || !Array.isArray(componentNodes) || !componentNodes.length) return false;
      const focusNodes = componentNodes;
      const focusNodeId = String(lineNode.id || '');
      const componentLabel = componentTokens.length ? componentTokens.join('/') : 'component';
      highlightHierarchyNode(lineNode);
      setIsolationMode(true, { frame: true });
      createDatafyBoxOverlay(focusNodes);
      createDatafyCallouts(lineNode, focusNodes, componentTokens);
      loadSelectionGeometry(lineNode, { status: false })
        .catch(() => false)
        .then(lineLoaded => {
          if (state.datafyLineNode?.id !== focusNodeId || state.datafyComponentNodes !== focusNodes) return null;
          createDatafyBoxOverlay(focusNodes);
          return loadDatafyComponentGeometry(focusNodes).then(datafyLoaded => ({ lineLoaded, datafyLoaded }));
        })
        .then(result => {
          if (!result) return;
          const lineMode = result.lineLoaded ? 'surface' : 'volume';
          const datafyMode = result.datafyLoaded ? 'surface' : 'volume';
          const termText = matchTerm ? ` inside ${matchTerm}` : '';
          setStatus(`3D line ${lineMode} in solid blue; DATAFY ${componentLabel} ${datafyMode} in pink${termText}.`);
        });
      return true;
    };
    const bboxVolume = bbox => {
      if (!bbox) return Number.POSITIVE_INFINITY;
      return Math.max(0.001, bbox[3] - bbox[0])
        * Math.max(0.001, bbox[4] - bbox[1])
        * Math.max(0.001, bbox[5] - bbox[2]);
    };
    const rayBboxDistance = (ray, bbox, padding = 0) => {
      if (!ray || !bbox) return Number.POSITIVE_INFINITY;
      let tMin = Number.NEGATIVE_INFINITY;
      let tMax = Number.POSITIVE_INFINITY;
      const axes = [
        ['x', 0, 3],
        ['y', 1, 4],
        ['z', 2, 5],
      ];
      for (const [axis, minIndex, maxIndex] of axes) {
        const origin = ray.origin[axis];
        const direction = ray.direction[axis];
        const min = bbox[minIndex] - padding;
        const max = bbox[maxIndex] + padding;
        if (Math.abs(direction) < 1e-9) {
          if (origin < min || origin > max) return Number.POSITIVE_INFINITY;
          continue;
        }
        let t1 = (min - origin) / direction;
        let t2 = (max - origin) / direction;
        if (t1 > t2) [t1, t2] = [t2, t1];
        tMin = Math.max(tMin, t1);
        tMax = Math.min(tMax, t2);
        if (tMax < tMin) return Number.POSITIVE_INFINITY;
      }
      if (tMax < 0) return Number.POSITIVE_INFINITY;
      return Math.max(tMin, 0);
    };
    const boxDistanceScore = (box, bbox) => {
      if (!box || !bbox || !state.THREE) return Number.POSITIVE_INFINITY;
      const nodeBox = boxFromBbox(bbox);
      if (!nodeBox) return Number.POSITIVE_INFINITY;
      const centerA = box.getCenter(new state.THREE.Vector3());
      const centerB = nodeBox.getCenter(new state.THREE.Vector3());
      const sizeA = box.getSize(new state.THREE.Vector3());
      const sizeB = nodeBox.getSize(new state.THREE.Vector3());
      return centerA.distanceTo(centerB)
        + Math.abs(sizeA.x - sizeB.x)
        + Math.abs(sizeA.y - sizeB.y)
        + Math.abs(sizeA.z - sizeB.z);
    };
    const hierarchyCandidatesForObject = object => {
      const names = [];
      let cursor = object;
      while (cursor && cursor !== state.model) {
        if (cursor.name) names.push(cursor.name);
        cursor = cursor.parent;
      }
      const candidates = [];
      const seen = new Set();
      names.forEach(name => {
        const exact = state.hierarchyByName.get(name) || [];
        const compact = state.hierarchyByCompactName.get(compactToken(name)) || [];
        [...exact, ...compact].forEach(item => {
          if (!item?.id || seen.has(item.id)) return;
          seen.add(item.id);
          candidates.push(item);
        });
      });
      return candidates;
    };
    const hierarchyNodeForObject = object => {
      let cursor = object;
      while (cursor && cursor !== state.model) {
        const id = cursor.userData?.hierarchyNodeId;
        if (id && state.hierarchyById.has(String(id))) return state.hierarchyById.get(String(id));
        cursor = cursor.parent;
      }
      const candidates = hierarchyCandidatesForObject(object);
      if (!candidates.length) return null;
      if (candidates.length === 1 && candidates[0].mesh) return candidates[0];
      const objectBox = new state.THREE.Box3().setFromObject(object);
      return candidates
        .filter(item => item.mesh || candidates.length === 1)
        .map(item => ({ item, score: boxDistanceScore(objectBox, item.bbox) + (item.mesh ? 0 : 1000) }))
        .sort((a, b) => a.score - b.score)[0]?.item || candidates[0];
    };
    const objectIsEffectivelyVisible = object => {
      let cursor = object;
      while (cursor && cursor !== state.scene) {
        if (cursor.visible === false) return false;
        cursor = cursor.parent;
      }
      return true;
    };
    const findHierarchyNodeByOverlayRay = () => {
      if (!state.raycaster) return null;
      const pick = root => {
        if (!root) return null;
        const hits = state.raycaster.intersectObjects([root], true)
          .filter(hit => objectIsEffectivelyVisible(hit.object));
        for (const hit of hits) {
          const node = hierarchyNodeForObject(hit.object);
          if (node?.bbox) return node;
        }
        return null;
      };
      return pick(state.datafyOverlay) || pick(state.selectionOverlay);
    };
    const findHierarchyNodeByMeshRay = () => {
      if (!state.model || !state.raycaster || !state.modelRaycastMeshes.length) return null;
      if (state.model.visible === false) return null;
      const hits = state.raycaster.intersectObjects(state.modelRaycastMeshes, false)
        .filter(hit => objectIsEffectivelyVisible(hit.object));
      for (const hit of hits) {
        const node = hierarchyNodeForObject(hit.object);
        if (node?.bbox) return node;
      }
      return null;
    };
    const findHierarchyNodeOnRay = (ray, options = {}) => {
      const scopedItems = Array.isArray(options.items) && options.items.length ? options.items : state.hierarchyItems;
      const pick = (meshOnly, padding) => {
        let bestNode = null;
        let bestScore = Number.POSITIVE_INFINITY;
        let bestVolume = Number.POSITIVE_INFINITY;
        scopedItems.forEach(item => {
          if (!item.bbox || (meshOnly && !item.mesh)) return;
          const distance = rayBboxDistance(ray, item.bbox, padding);
          if (!Number.isFinite(distance)) return;
          const volume = bboxVolume(item.bbox);
          const score = distance + Math.log10(volume + 1) * 0.0005 - Math.min(item.depth, 100) * 0.000001;
          if (score < bestScore || (Math.abs(score - bestScore) < 1e-7 && volume < bestVolume)) {
            bestNode = item;
            bestScore = score;
            bestVolume = volume;
          }
        });
        return bestNode;
      };
      return pick(true, 0.01) || pick(false, 0.01);
    };
    const scrollSelectedHierarchyIntoView = () => {
      if (!modelList || !state.selectedHierarchyId) return;
      window.setTimeout(() => {
        const safeId = String(state.selectedHierarchyId).replace(/["\\]/g, '\\$&');
        const item = modelList.querySelector(`[data-model-node-id="${safeId}"]`);
        item?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }, 0);
    };
    const revealHierarchyNode = (node, source = 'tree') => {
      if (!node) return;
      state.selectedHierarchyId = node.id;
      let parentId = node.parent;
      while (parentId) {
        state.hierarchyExpanded.add(parentId);
        parentId = state.hierarchyById.get(parentId)?.parent || '';
      }
      if (source === 'viewer' && queryInput) {
        queryInput.value = '';
        state.query = '';
        state.queryTokens = [];
        renderWbs();
      }
      setActiveTab('model');
      renderModelTree();
      scrollSelectedHierarchyIntoView();
    };
    const selectHierarchyNode = (node, source = 'tree', options = {}) => {
      if (!node) return;
      if (!options.preserveDatafyFocus) {
        clearDatafyFocus();
      }
      state.supplyContext = options.supplyContext || null;
      revealHierarchyNode(node, source);
      setSelection({
        label: node.name,
        type: `${node.mesh ? 'Mesh' : 'Group'} - Node ${node.id}`,
        supplyContext: state.supplyContext,
      });
      if (!state.modelLoaded) {
        updateIsolationControls();
        setStatus(`Selected in hierarchy: ${node.name}. The 3D model is still loading.`);
        return;
      }
      if (options.skipModelHighlight) {
        updateIsolationControls();
        setStatus(`Selected in current 3D focus: ${node.name}`);
        renderOnce();
        return;
      }
      highlightHierarchyNode(node);
      loadSelectionGeometry(node);
    };
    const supplyLineCandidates = value => {
      return String(value || '')
        .split(/[,;\n]+/)
        .map(part => part.replace(/\s+\+\d+\s*$/g, '').trim())
        .filter(part => {
          const norm = normalize(part).trim();
          return part && !['-', '--', 'n/a', 'na', 'none', 'null'].includes(norm);
        })
        .slice(0, 16);
    };
    const findHierarchyNodeBySupplyLine = candidates => {
      const terms = candidates
        .map(term => ({
          term,
          norm: normalize(term).replace(/\s+/g, ''),
          compact: compactToken(term),
        }))
        .filter(item => item.compact.length >= 5);
      if (!terms.length || !state.hierarchyItems.length) return null;
      let best = null;
      state.hierarchyItems.forEach(item => {
        if (!item.bbox) return;
        const nameNorm = normalize(item.name).replace(/\s+/g, '');
        const compact = item.compactSearch || compactToken(item.name);
        terms.forEach(candidate => {
          let score = Number.POSITIVE_INFINITY;
          if (candidate.norm && (nameNorm === `/${candidate.norm}` || nameNorm.includes(`/${candidate.norm}/`))) {
            score = 0;
          } else if (candidate.norm && nameNorm.includes(candidate.norm)) {
            score = 8;
          } else if (candidate.compact.length >= 7 && compact.includes(candidate.compact)) {
            score = 18;
          }
          if (!Number.isFinite(score)) return;
          if (item.mesh) score += 4;
          if (!item.children) score += 2;
          score += Math.max(0, Number(item.depth || 0) - 5) * 0.04;
          score += Math.log10(bboxVolume(item.bbox) + 1) * 0.0002;
          if (!best || score < best.score) best = { node: item, term: candidate.term, score };
        });
      });
      return best;
    };
    const focusSupplyLineIn3D = async detail => {
      const candidates = supplyLineCandidates(detail?.line);
      const trigger = detail?.trigger instanceof Element ? detail.trigger : null;
      document.querySelectorAll('.c3-line-3d-link.is-pending, .c3-line-3d-link.is-match, .c3-line-3d-link.is-miss, .c3-3d-click-hint.is-pending, .c3-3d-click-hint.is-match, .c3-3d-click-hint.is-miss').forEach(el => {
        el.classList.remove('is-pending', 'is-match', 'is-miss');
      });
      if (!candidates.length) {
        setSelection({ label: 'No 3D match', type: 'Selected supply row has no line number.' });
        setStatus('No 3D match: selected supply row has no line number.');
        window.dispatchEvent(new CustomEvent('c3:line-lookup-status', {
          detail: { text: 'No 3D match: selected row has no line number.', state: 'miss' },
        }));
        return false;
      }
      trigger?.classList.add('is-pending');
      root.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setActiveTab('model');
      setStatus(`Searching 3D index for line ${candidates[0]}...`);
      window.dispatchEvent(new CustomEvent('c3:line-lookup-status', {
        detail: { text: `Searching 3D line ${candidates[0]}...`, state: 'pending' },
      }));
      await loadHierarchy();
      const match = findHierarchyNodeBySupplyLine(candidates);
      if (!match?.node) {
        trigger?.classList.remove('is-pending');
        trigger?.classList.add('is-miss');
        setSelection({
          label: 'No 3D match',
          type: `Line ${candidates[0]}${detail?.drawing ? ` - ${detail.drawing}` : ''}`,
        });
        setStatus(`No 3D match for line ${candidates[0]}.`);
        window.dispatchEvent(new CustomEvent('c3:line-lookup-status', {
          detail: { text: `No 3D match for ${candidates[0]}.`, state: 'miss' },
        }));
        return false;
      }
      if (queryInput) {
        queryInput.value = match.term;
        state.query = normalize(match.term).trim();
        state.queryTokens = state.query.split(/[^a-z0-9]+/).filter(token => token.length >= 2);
        renderWbs();
        renderModelTree();
      }
      if (!state.modelLoaded && !state.modelLoading) {
        await loadModel('overview');
      }
      let supplyContext = detail?.datafy || null;
      if (supplyContext) {
        supplyContext = { ...supplyContext, requiresDatafyLookup: true };
        try {
          const materialPayload = await loadDatafyMaterialItems(supplyContext);
          if (materialPayload && Array.isArray(materialPayload.rows)) {
            supplyContext = {
              ...supplyContext,
              items: materialPayload.rows,
              families: Array.isArray(materialPayload.families) ? materialPayload.families : supplyContext.families,
              tokens: Array.isArray(materialPayload.tokens) ? materialPayload.tokens : supplyContext.tokens,
              pending: Number(materialPayload.missing_item_count ?? supplyContext.pending ?? 0),
              missingQtyTotal: Number(materialPayload.missing_qty_total || 0),
              materialTotal: Number(materialPayload.total || materialPayload.rows.length || 0),
              attentionCount: Number(materialPayload.attention_item_count || 0),
              materialLookupLoaded: true,
            };
          } else {
            supplyContext = {
              ...supplyContext,
              items: [],
              families: [],
              tokens: [],
              pending: 0,
              materialLookupLoaded: false,
            };
          }
        } catch (error) {
          console.warn('DATAFY material lookup failed', error);
          supplyContext = {
            ...supplyContext,
            items: [],
            families: [],
            tokens: [],
            pending: 0,
            materialLookupLoaded: false,
            materialLookupFailed: true,
          };
        }
      }
      const componentMatch = supplyContext ? findSupplyComponentNodes(candidates, supplyContext, match.node) : { tokens: [], nodes: [] };
      if (supplyContext && componentMatch.nodes.length) {
        state.supplyContext = {
          ...supplyContext,
          tokens: componentMatch.tokens,
          componentCount: componentMatch.nodes.length,
        };
        state.datafyLineNode = match.node;
        state.datafyComponentNodes = componentMatch.nodes;
        state.datafyComponentTokens = componentMatch.tokens;
        revealHierarchyNode(match.node, 'supply-line');
        setSelection({
          label: match.node.name,
          type: `DATAFY focus - ${componentMatch.nodes.length} ${componentMatch.tokens.join('/')} component(s) marked`,
          supplyContext: state.supplyContext,
        });
        if (state.modelLoaded) {
          renderDatafyFocusOverlays(match.node, componentMatch.nodes, componentMatch.tokens, match.term);
        } else {
          state.isolateSelection = true;
          updateIsolationControls();
        }
      } else {
        if (supplyContext) {
          state.supplyContext = {
            ...supplyContext,
            tokens: componentMatch.tokens,
            componentCount: 0,
          };
          state.datafyLineNode = match.node;
          state.datafyComponentNodes = [];
          state.datafyComponentTokens = componentMatch.tokens;
        }
        selectHierarchyNode(match.node, 'supply-line', { supplyContext: state.supplyContext || supplyContext, preserveDatafyFocus: !!supplyContext });
        if (state.modelLoaded) {
          setIsolationMode(true, { frame: true });
          if (supplyContext && Array.isArray(supplyContext.items) && supplyContext.items.length) {
            createDatafyCallouts(match.node, [], componentMatch.tokens);
          }
        } else {
          state.isolateSelection = true;
          updateIsolationControls();
        }
      }
      if (componentMatch.tokens.length && supplyContext && !componentMatch.nodes.length) {
        setStatus(`3D line isolated, but no ${componentMatch.tokens.join('/')} component was found inside ${match.term}.`);
      } else if (supplyContext && componentMatch.nodes.length) {
        setStatus(`3D line context in blue; ${componentMatch.nodes.length} ${componentMatch.tokens.join('/')} component(s) marked from DATAFY.`);
      } else {
        setStatus(`3D match: ${match.term} - ${match.node.name}`);
      }
      trigger?.classList.remove('is-pending', 'is-miss');
      trigger?.classList.add('is-match');
      window.setTimeout(() => trigger?.classList.remove('is-match'), 1600);
      window.dispatchEvent(new CustomEvent('c3:line-lookup-status', {
        detail: { text: supplyContext ? `DATAFY components linked: ${match.term}` : `3D match found: ${match.term}`, state: 'match' },
      }));
      return true;
    };
    root._focusSupplyLineIn3D = focusSupplyLineIn3D;
    const handleViewerClick = async event => {
      if (!state.modelLoaded || !state.camera || !state.renderer || !state.raycaster || !state.THREE) return;
      if (!state.hierarchyLoaded) {
        setStatus('Loading hierarchy to identify the 3D click...');
        await loadHierarchy();
      }
      if (!state.hierarchyLoaded) return;
      const rect = state.renderer.domElement.getBoundingClientRect();
      const pointer = new state.THREE.Vector2(
        ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1,
        -(((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 - 1),
      );
      state.controls?.update();
      state.camera.updateMatrixWorld(true);
      state.raycaster.setFromCamera(pointer, state.camera);
      const focusScope = datafyPickScopeNodes();
      const selectedScope = selectedHierarchyNode();
      const scopedFallback = focusScope.length
        ? focusScope
        : (state.isolateSelection && selectedScope ? [selectedScope] : []);
      const isScopedView = state.isolateSelection || state.model?.visible === false || focusScope.length > 0;
      let node = findHierarchyNodeByOverlayRay();
      if (!node && scopedFallback.length) {
        node = findHierarchyNodeOnRay(state.raycaster.ray, { items: scopedFallback });
      }
      if (!node && !isScopedView) {
        node = findHierarchyNodeByMeshRay() || findHierarchyNodeOnRay(state.raycaster.ray);
      }
      if (!node) {
        setStatus('3D click is outside a recognized model item.');
        return;
      }
      const preserveDatafyFocus = nodeIsInDatafyFocus(node);
      selectHierarchyNode(node, 'viewer', {
        preserveDatafyFocus,
        supplyContext: preserveDatafyFocus ? state.supplyContext : null,
        skipModelHighlight: preserveDatafyFocus,
      });
    };
    const indexModel = object => {
      const items = [];
      const raycastMeshes = [];
      object.traverse(child => {
        if (!child.name && !child.isMesh) return;
        let depth = 0;
        let parent = child.parent;
        while (parent && parent !== object) {
          depth += 1;
          parent = parent.parent;
        }
        let meshes = 0;
        child.traverse?.(descendant => { if (descendant.isMesh) meshes += 1; });
        items.push({
          uuid: child.uuid,
          name: child.name || `Mesh ${items.length + 1}`,
          type: child.type || 'Object3D',
          depth,
          meshes: meshes || (child.isMesh ? 1 : 0),
          object: child,
        });
        if (child.isMesh && child.geometry) {
          const node = hierarchyNodeForObject(child);
          if (node?.id) child.userData.hierarchyNodeId = node.id;
          raycastMeshes.push(child);
        }
      });
      state.modelItems = items.filter(item => item.meshes > 0).slice(0, 2000);
      state.modelRaycastMeshes = raycastMeshes;
      renderModelTree();
    };
    const disposeObject = object => {
      object?.traverse?.(child => {
        child.geometry?.dispose?.();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach(material => material?.dispose?.());
      });
    };
    const startRenderLoop = () => {
      if (state.renderFrame || !state.renderer || !state.scene || !state.camera) return;
      const animate = () => {
        if (!state.viewerVisible || !state.renderer || !state.scene || !state.camera) {
          state.renderFrame = null;
          return;
        }
        state.controls?.update();
        state.renderer.render(state.scene, state.camera);
        updateDatafyCallouts();
        state.renderFrame = requestAnimationFrame(animate);
      };
      state.renderFrame = requestAnimationFrame(animate);
    };
    const stopRenderLoop = () => {
      if (state.renderFrame) {
        cancelAnimationFrame(state.renderFrame);
        state.renderFrame = null;
      }
    };
    const renderOnce = () => {
      if (!state.renderer || !state.scene || !state.camera) return;
      state.renderer.render(state.scene, state.camera);
      updateDatafyCallouts();
    };
    const requestIdle = callback => {
      if ('requestIdleCallback' in window) {
        window.requestIdleCallback(callback, { timeout: 2200 });
      } else {
        setTimeout(callback, 900);
      }
    };
    const queueDetailLoad = () => {
      if (state.autoRefineStarted || !modelUrls.detail || modelUrls.detail === modelUrls.overview) return;
      state.autoRefineStarted = true;
      state.pendingDetail = true;
      setLoadButton(true, '<i class="bi bi-hourglass-split"></i> Waiting for HQ');
      setStatus('Fast preview ready. HQ will refine when the browser is idle.');
      requestIdle(() => {
        if (!state.pendingDetail || state.currentModelMode === 'detail') return;
        if (!state.viewerVisible) {
          setLoadButton(false, '<i class="bi bi-layers"></i> Load HQ');
          setStatus('Fast preview ready. HQ paused until this section returns to the screen.');
          return;
        }
        state.pendingDetail = false;
        loadModel('detail');
      });
    };
    const ensureViewer = async () => {
      if (state.loader) return;
      const THREE = await import('three');
      const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
      const { MeshoptDecoder } = await import('three/addons/libs/meshopt_decoder.module.js');
      state.THREE = THREE;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x0f172a);
      const camera = new THREE.PerspectiveCamera(45, Math.max(viewer.clientWidth, 1) / Math.max(viewer.clientHeight, 1), 0.1, 100000);
      const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance' });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
      renderer.setSize(viewer.clientWidth, viewer.clientHeight);
      viewer.innerHTML = '';
      viewer.appendChild(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x94a3b8, 1.25));
      const sun = new THREE.DirectionalLight(0xffffff, 1.4);
      sun.position.set(6, 10, 8);
      scene.add(sun);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
      controls.screenSpacePanning = true;
      const loader = new GLTFLoader();
      loader.setMeshoptDecoder(MeshoptDecoder);
      const raycaster = new THREE.Raycaster();
      renderer.domElement.style.touchAction = 'none';
      renderer.domElement.addEventListener('pointerdown', event => {
        state.pointerDown = { x: event.clientX, y: event.clientY, t: performance.now() };
      });
      renderer.domElement.addEventListener('pointerup', event => {
        const down = state.pointerDown;
        state.pointerDown = null;
        if (!down) return;
        const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y);
        const elapsed = performance.now() - down.t;
        if (moved > 6 || elapsed > 900) return;
        handleViewerClick(event);
      });
      Object.assign(state, { scene, camera, renderer, controls, loader, raycaster });
      const observer = new ResizeObserver(() => {
        if (!state.renderer || !state.camera) return;
        state.camera.aspect = Math.max(viewer.clientWidth, 1) / Math.max(viewer.clientHeight, 1);
        state.camera.updateProjectionMatrix();
        state.renderer.setSize(viewer.clientWidth, viewer.clientHeight);
        renderOnce();
      });
      observer.observe(viewer);
      state.animationStarted = true;
      if (state.viewerVisible) startRenderLoop();
    };
    const loadModel = async (mode = 'overview') => {
      if (state.modelLoading || !viewer || state.currentModelMode === mode) return;
      const isDetail = mode === 'detail';
      const url = isDetail ? modelUrls.detail : modelUrls.overview;
      const label = isDetail ? 'refined model' : '3D fast preview';
      if (!url) {
        setStatus('3D file is not configured.');
        return;
      }
      const started = performance.now();
      state.modelLoading = true;
      setLoadButton(true, `<i class="bi bi-hourglass-split"></i> Loading ${isDetail ? 'detail' : '3D'}...`);
      setStatus(`Downloading ${label}...`);
      try {
        await ensureViewer();
        const gltf = await state.loader.loadAsync(url, event => {
          if (event.total) {
            const pct = Math.round((event.loaded / event.total) * 100);
            setStatus(`Loading ${label}... ${pct}%`);
          }
        });
        resetHighlights();
        if (state.model) {
          state.scene.remove(state.model);
          disposeObject(state.model);
        }
        state.model = gltf.scene;
        state.scene.add(gltf.scene);
        state.modelLoaded = true;
        state.modelLoading = false;
        state.currentModelMode = mode;
        setModelControlsEnabled(true);
        emptyState?.remove();
        indexModel(gltf.scene);
        const selectedNode = state.hierarchyById.get(state.selectedHierarchyId);
        if (selectedNode?.bbox) {
          if (state.supplyContext && state.datafyLineNode?.id === selectedNode.id && state.datafyComponentNodes.length) {
            renderDatafyFocusOverlays(selectedNode, state.datafyComponentNodes, state.datafyComponentTokens);
          } else {
            highlightHierarchyNode(selectedNode);
            loadSelectionGeometry(selectedNode);
          }
        } else {
          state.isolateSelection = false;
          applyIsolationVisibility({ render: false });
          frameModel();
        }
        updateIsolationControls();
        renderOnce();
        if (state.viewerVisible) startRenderLoop();
        const elapsed = ((performance.now() - started) / 1000).toFixed(1);
        const itemLabel = state.modelItems.length === 1 ? 'indexed object' : 'indexed objects';
        const shouldAutoRefine = !isDetail
          && root.dataset.modelAutoRefine === 'true'
          && !state.autoRefineStarted
          && modelUrls.detail
          && modelUrls.detail !== modelUrls.overview;
        if (shouldAutoRefine) {
          setStatus(`Fast preview ready in ${elapsed}s. Preparing HQ without blocking the page...`);
          queueDetailLoad();
        } else if (isDetail || modelUrls.detail === modelUrls.overview) {
          setLoadButton(true, '<i class="bi bi-check2"></i> Refined model');
          setStatus(`Refined model ready in ${elapsed}s. ${state.modelItems.length} ${itemLabel}.`);
        } else {
          setLoadButton(false, '<i class="bi bi-layers"></i> Refine detail');
          setStatus(`Fast preview ready in ${elapsed}s. Refinement available on demand.`);
        }
      } catch (error) {
        state.modelLoading = false;
        setLoadButton(false, `<i class="bi bi-play-fill"></i> Retry ${isDetail ? 'detail' : '3D'}`);
        setStatus(`Failed to load ${label}: ${error?.message || 'unknown error'}`);
      }
    };

    queryInput?.addEventListener('input', () => {
      clearDatafyFocus();
      state.datafyRequestId += 1;
      removeDatafyOverlay();
      state.query = normalize(queryInput.value).trim();
      state.queryTokens = state.query.split(/[^a-z0-9]+/).filter(token => token.length >= 2);
      const wbsCount = renderWbs() || 0;
      renderModelTree();
      if (state.query.length >= 2 && (state.activeTab === 'model' || wbsCount === 0)) {
        setActiveTab('model');
      }
    });
    tabs.forEach(button => button.addEventListener('click', () => setActiveTab(button.dataset.projectTab)));
    wbsList?.addEventListener('click', event => {
      const item = event.target.closest('[data-wbs-id]');
      if (!item) return;
      const node = byId.get(item.dataset.wbsId);
      if (!node) return;
      if (childrenOf(node.id).length && event.target.closest('.dx-project-tree-caret')) {
        state.expanded.has(node.id) ? state.expanded.delete(node.id) : state.expanded.add(node.id);
        renderWbs();
        return;
      }
      clearDatafyFocus();
      setSelection(node);
      highlightByTerms(node);
    });
    modelList?.addEventListener('click', event => {
      const item = event.target.closest('[data-model-node-id]');
      if (!item) return;
      const node = state.hierarchyById.get(item.dataset.modelNodeId);
      if (!node) return;
      const children = hierarchyChildrenOf(node.id);
      if (children.length && event.target.closest('.dx-project-tree-caret')) {
        state.hierarchyExpanded.has(node.id) ? state.hierarchyExpanded.delete(node.id) : state.hierarchyExpanded.add(node.id);
        renderModelTree();
        return;
      }
      selectHierarchyNode(node, 'tree');
    });
    loadButton?.addEventListener('click', () => {
      loadModel(state.currentModelMode === 'overview' ? 'detail' : 'overview');
    });
    fitButton?.addEventListener('click', frameModel);
    isolateButton?.addEventListener('click', () => {
      setIsolationMode(!state.isolateSelection);
    });
    clearButton?.addEventListener('click', () => {
      state.isolateSelection = false;
      state.selectionRequestId += 1;
      if (state.model) state.model.visible = true;
      resetHighlights();
      state.selectedHierarchyId = '';
      clearDatafyFocus();
      state.datafyRequestId += 1;
      root.classList.remove('is-isolating-selection');
      renderModelTree();
      setSelection(null);
      updateIsolationControls();
      setStatus(state.modelLoaded ? 'Focus cleared. 3D model loaded.' : 'Focus cleared.');
      renderOnce();
    });
    root.addEventListener('c3:supply-line-focus', event => {
      focusSupplyLineIn3D(event.detail || {});
    });
    renderWbs();
    renderModelTree();
    setActiveTab(defaultTab);
    const activateViewer = () => {
      state.viewerVisible = true;
      if (state.modelLoaded) startRenderLoop();
      if (state.pendingDetail && state.currentModelMode === 'overview' && !state.modelLoading) {
        state.pendingDetail = false;
        loadModel('detail');
      } else if (root.dataset.modelAutoload === 'true' && !state.modelLoaded && !state.modelLoading) {
        loadModel('overview');
      }
    };
    const deactivateViewer = () => {
      state.viewerVisible = false;
      stopRenderLoop();
    };
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) activateViewer();
          else deactivateViewer();
        });
      }, { rootMargin: '900px 0px 900px 0px', threshold: 0.01 });
      observer.observe(root);
    } else if (root.dataset.modelAutoload === 'true') {
      state.viewerVisible = true;
      setTimeout(() => loadModel('overview'), 250);
    }
  };

  const setSupplyCampaignMode = (root, mode) => {
    if (!root || !mode) return;
    const buttons = Array.from(root.querySelectorAll('[data-supply-mode]'));
    const views = Array.from(root.querySelectorAll('[data-supply-scope]'));
    buttons.forEach(button => {
      const active = button.dataset.supplyMode === mode;
      button.classList.toggle('is-active', active);
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    views.forEach(view => {
      view.classList.toggle('is-active', view.dataset.supplyScope === mode);
    });
    if (typeof window.c3RenderPoPlacedScope === 'function') {
      window.requestAnimationFrame(() => window.c3RenderPoPlacedScope(mode));
    }
  };
  const initSupplyCampaignPanel = root => {
    const buttons = Array.from(root.querySelectorAll('[data-supply-mode]'));
    buttons.forEach(button => {
      const active = button.classList.contains('is-active') || button.classList.contains('active');
      button.classList.toggle('is-active', active);
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  };

  document.querySelectorAll('[data-supply-campaign-panel]').forEach(initSupplyCampaignPanel);
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-supply-mode]');
    if (!button) return;
    const root = button.closest('[data-supply-campaign-panel]');
    if (!root) return;
    setSupplyCampaignMode(root, button.dataset.supplyMode);
  });

  const supplyLineLookupHasValue = value => {
    const norm = String(value || '').trim().toLowerCase();
    return !!norm && !['-', '--', 'n/a', 'na', 'none', 'null'].includes(norm);
  };
  const showLineLookupToast = (text, state = 'pending') => {
    if (!text) return;
    let toast = document.querySelector('[data-c3-line-lookup-toast]');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'c3-line-lookup-toast';
      toast.setAttribute('data-c3-line-lookup-toast', '');
      document.body.appendChild(toast);
    }
    toast.classList.remove('is-pending', 'is-match', 'is-miss');
    toast.classList.add(`is-${state || 'pending'}`, 'is-visible');
    toast.textContent = text;
    clearTimeout(toast._hideTimer);
    toast._hideTimer = window.setTimeout(() => {
      toast.classList.remove('is-visible');
    }, state === 'pending' ? 3200 : 5200);
  };
  window.addEventListener('c3:line-lookup-status', event => {
    showLineLookupToast(event.detail?.text || '', event.detail?.state || 'pending');
  });
  document.querySelectorAll('[data-project-3d]').forEach(initProjectConsult3D);
  const parseDatafyNumber = value => {
    const raw = String(value || '0').trim();
    const normalized = raw.includes(',') ? raw.replace(/\./g, '').replace(',', '.') : raw;
    const num = Number.parseFloat(normalized);
    return Number.isFinite(num) ? num : 0;
  };
  const datafyContextFromRow = (row, line, drawing) => {
    if (!row) return null;
    const cell = column => row.querySelector(`[data-col="${column}"]`);
    const cellText = column => cell(column)?.textContent?.replace(/\s+/g, ' ').trim() || '';
    const cellNumber = column => parseDatafyNumber(cell(column)?.getAttribute('data-sort-value') || cellText(column));
    const pending = parseDatafyNumber(
      row.getAttribute('data-c3-datafy-pending')
      || row.getAttribute('data-drawing-pending')
      || row.getAttribute('data-missing-qty')
    );
    const familyText = row.getAttribute('data-c3-datafy-families')
      || row.getAttribute('data-c3-datafy-family')
      || row.querySelector('[data-col="family"]')?.textContent
      || '';
    const families = familyText
      .split(/[,;|]+/)
      .map(item => item.trim())
      .filter(item => item && !['-', 'n/a', 'N/A'].includes(item))
      .slice(0, 10);
    const code = row.getAttribute('data-c3-datafy-code') || row.querySelector('[data-col="code"]')?.textContent?.trim() || '';
    const description = row.getAttribute('data-c3-datafy-description') || row.querySelector('[data-col="description"]')?.textContent?.trim() || '';
    const status = row.getAttribute('data-c3-datafy-status') || row.getAttribute('data-status') || '';
    const scope = row.getAttribute('data-scope') || '';
    const scopeLabel = cellText('scope');
    const requested = cellNumber('requested');
    const allocated = cellNumber('allocated');
    const missing = cellNumber('missing') || pending;
    const stock = cellNumber('stock');
    const family = cellText('family') || families[0] || '';
    const po = cellText('po');
    const total = cellNumber('total') || parseDatafyNumber(row.getAttribute('data-stage-total-items'));
    const covered = cellNumber('covered') || parseDatafyNumber(row.getAttribute('data-stage-po-items')) || parseDatafyNumber(row.getAttribute('data-with-po'));
    const withPo = parseDatafyNumber(row.getAttribute('data-stage-po-items') || row.getAttribute('data-with-po'));
    const withoutPo = parseDatafyNumber(row.getAttribute('data-stage-no-po-items') || row.getAttribute('data-without-po'));
    const poNotArrived = parseDatafyNumber(row.getAttribute('data-stage-no-yard-items') || row.getAttribute('data-po-not-arrived'));
    const yardActual = parseDatafyNumber(row.getAttribute('data-stage-yard-items') || row.getAttribute('data-yard-actual'));
    const items = [];
    if (code || description || family || requested || allocated || missing || stock || po) {
      items.push({
        code,
        description,
        family,
        requested,
        requested_qty: requested,
        allocated,
        allocated_qty: allocated,
        missing,
        missing_qty: missing,
        stock,
        stock_free_qty: stock,
        po,
        status,
        scope,
        scope_label: scopeLabel,
      });
    }
    if (!pending && !families.length && !code && !description && !status && !total && !items.length) return null;
    return {
      pending,
      families,
      code,
      description,
      status,
      scope,
      scopeLabel,
      line,
      drawing,
      total,
      covered,
      withPo,
      withoutPo,
      poNotArrived,
      yardActual,
      items,
    };
  };
  document.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target : event.target?.parentElement;
    if (!target) return;
    const directTrigger = target.closest('[data-c3-3d-line-trigger]');
    let source = directTrigger;
    if (!source) {
      const cell = target.closest('[data-col="drawing"], [data-col="line"]');
      source = cell?.closest('[data-grid-row][data-c3-3d-line]');
    }
    if (!source) return;
    const line = source.getAttribute('data-c3-3d-line') || '';
    const drawing = source.getAttribute('data-c3-3d-drawing') || source.closest('[data-grid-row]')?.getAttribute('data-c3-3d-drawing') || '';
    if (!supplyLineLookupHasValue(line)) return;
    const project3d = document.querySelector('[data-project-3d]');
    if (!project3d) return;
    event.preventDefault();
    event.stopPropagation();
    const row = source.closest('[data-grid-row]');
    const detail = { line, drawing, trigger: directTrigger || source, datafy: datafyContextFromRow(row, line, drawing) };
    showLineLookupToast(`Searching 3D line ${line.split(/[,;\n]+/)[0].trim()}...`, 'pending');
    if (typeof project3d._focusSupplyLineIn3D === 'function') {
      project3d._focusSupplyLineIn3D(detail).catch(error => {
        showLineLookupToast(`3D lookup failed: ${error?.message || 'unknown error'}`, 'miss');
      });
      return;
    }
    project3d.dispatchEvent(new CustomEvent('c3:supply-line-focus', { detail }));
  }, true);

  // Tooltips
  if (window.bootstrap) {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => new bootstrap.Tooltip(el));
  }
})();

/**
 * Render a Plotly chart given a DOM id and config returned by the backend.
 * Backend sends: { data: [...], layout: {...}, config: {...} }
 */
window.renderShellChart = function (elementId, payload) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const nextFrame = callback => {
    if (window.requestAnimationFrame) window.requestAnimationFrame(callback);
    else window.setTimeout(callback, 16);
  };
  const runWhenVisible = callback => {
    const rect = el.getBoundingClientRect();
    if (rect.top < window.innerHeight + 420 && rect.bottom > -160) {
      nextFrame(callback);
      return;
    }
    if (!('IntersectionObserver' in window)) {
      nextFrame(callback);
      return;
    }
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        nextFrame(callback);
      });
    }, { rootMargin: '520px 0px', threshold: 0.01 });
    observer.observe(el);
  };
  const numericArray = values => Array.isArray(values) && values.some(value => Number.isFinite(Number(value)));
  const seedTrace = trace => {
    const next = Object.assign({}, trace);
    if ((trace.type === 'bar' || trace.type === undefined) && trace.orientation === 'h' && numericArray(trace.x)) {
      next.x = trace.x.map(() => 0);
      return next;
    }
    if ((trace.type === 'bar' || trace.type === 'scatter' || trace.type === undefined) && numericArray(trace.y)) {
      next.y = trace.y.map(() => 0);
      return next;
    }
    return trace;
  };
  const render = () => {
    if (!window.Plotly) {
      window.setTimeout(render, 50);
      return;
    }
    const data = (payload && payload.data) || [];
    const layout = Object.assign({
      margin: { l: 50, r: 20, t: 30, b: 50 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { family: 'Inter, sans-serif', size: 12 },
      legend: { orientation: 'h', y: -0.2 },
      transition: { duration: 420, easing: 'cubic-in-out' },
    }, payload.layout || {});
    const config = Object.assign({
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
      locale: 'pt-BR',
    }, payload.config || {});
    el.classList.add('is-chart-loading');
    const seedData = data.map(seedTrace);
    Plotly.newPlot(el, seedData, layout, config).then(() => {
      const animated = seedData.some((trace, index) => trace !== data[index]);
      if (animated) {
        return Plotly.animate(el, { data }, {
          transition: { duration: 460, easing: 'cubic-in-out' },
          frame: { duration: 460, redraw: false },
        });
      }
      return null;
    }).finally(() => {
      el.classList.remove('is-chart-loading');
      el.classList.add('is-chart-ready');
    });
  };
  runWhenVisible(render);
};
