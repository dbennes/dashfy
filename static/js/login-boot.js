(function () {
  'use strict';

  function initLoginBoot() {
    var root = document.querySelector('[data-login-boot]');
    if (!root || root.dataset.loginBootStarted === '1') return;
    root.dataset.loginBootStarted = '1';

    var log = root.querySelector('[data-login-boot-log]');
    var bar = root.querySelector('[data-login-boot-bar]');
    var pct = root.querySelector('[data-login-boot-pct]');
    var engage = root.querySelector('[data-login-boot-engage]');
    var stats = {
      params: root.querySelector('[data-boot-stat="params"]'),
      ops: root.querySelector('[data-boot-stat="ops"]'),
      alerts: root.querySelector('[data-boot-stat="alerts"]')
    };
    var modules = new Map(
      Array.from(root.querySelectorAll('[data-boot-module]')).map(function (item) {
        return [item.dataset.bootModule, item];
      })
    );
    var steps = [
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
      { time: '00:02.438', state: 'ok', mark: 'OK', text: 'Construction cockpit ready' }
    ];
    var current = 0;
    var progress = 0;
    var finished = false;
    var timers = [];

    function setModule(name, state) {
      var item = modules.get(name);
      if (!item) return;
      var status = item.querySelector('.status');
      item.classList.toggle('is-working', state === 'work');
      item.classList.toggle('is-on', state === 'ok');
      if (status) status.textContent = state === 'ok' ? 'ONLINE' : 'BOOTING';
    }

    function appendLine(step) {
      if (!log) return;
      var line = document.createElement('div');
      line.className = 'c3-boot-log-line ' + (step.state || 'info');
      line.innerHTML = [
        '<span class="t">' + step.time + '</span>',
        '<span class="s">' + step.mark + '</span>',
        '<span class="msg">' + step.text + '</span>'
      ].join('');
      log.appendChild(line);
      while (log.children.length > 8) log.firstElementChild.remove();
      log.scrollTop = log.scrollHeight;
    }

    function setProgress(value) {
      progress = Math.max(progress, Math.min(100, Math.round(value)));
      if (bar) bar.style.width = progress + '%';
      if (pct) pct.textContent = progress + '%';
    }

    function clearTimers() {
      timers.forEach(function (timer) { clearTimeout(timer); });
      timers.length = 0;
      if (root._bootStatsTimer) clearInterval(root._bootStatsTimer);
    }

    function finish() {
      if (finished) return;
      finished = true;
      clearTimers();
      Array.from(modules.keys()).forEach(function (name) { setModule(name, 'ok'); });
      setProgress(100);
      if (engage) engage.classList.add('is-visible');
      if (document.body) {
        document.body.classList.remove('has-login-boot');
        document.body.classList.add('login-boot-ready');
      }
      timers.push(setTimeout(function () {
        root.classList.add('is-fading');
        timers.push(setTimeout(function () { root.remove(); }, 360));
      }, 260));
    }

    function tick() {
      if (finished) return;
      var step = steps[current];
      if (!step) {
        finish();
        return;
      }
      if (step.module) setModule(step.module, step.done ? 'ok' : 'work');
      appendLine(step);
      setProgress(((current + 1) / steps.length) * 100);
      current += 1;
      timers.push(setTimeout(tick, current < 4 ? 70 : 90));
    }

    root._bootStatsTimer = setInterval(function () {
      var seed = Date.now() / 700;
      if (stats.params) stats.params.textContent = String(1830 + Math.floor(Math.sin(seed) * 22 + 34));
      if (stats.ops) stats.ops.textContent = String(92 + Math.floor(Math.cos(seed) * 4 + 4));
      if (stats.alerts) stats.alerts.textContent = String(Math.max(0, 3 + Math.floor(Math.sin(seed * 1.7) * 2)));
    }, 160);

    root.addEventListener('click', finish);
    root.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' || event.key === 'Enter' || event.key === ' ') finish();
    });
    root.setAttribute('tabindex', '-1');
    try { root.focus({ preventScroll: true }); } catch (error) {}
    tick();
  }

  initLoginBoot();
})();
