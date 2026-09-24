(function () {
  "use strict";
  const dialog = document.getElementById("sectionNotesDialog");
  if (!dialog || !dialog.showModal) return;
  const legacyLabels = {s00:"Planning", s01:"Engineering", s02:"Supply", s03:"Fabrication", s04:"Logistics", s05:"3D model"};
  const panels = new Map(Array.from(document.querySelectorAll("[data-note-panel]"), node => [node.dataset.notePanel, node]));
  const labels = {...legacyLabels, ...Object.fromEntries(Array.from(panels, ([key,node]) => [key,node.dataset.noteLabel]))};
  const legacyButton = document.querySelector("[data-sn-legacy]");
  const legacySelect = dialog.querySelector("[data-sn-legacy-select]");
  const legacyLabel = dialog.querySelector("[data-sn-legacy-label]");
  function scopeParams() { return panels.has(section) ? {panel:section} : {section}; }
  const statuses = {pending:"Pending", resolved:"Resolved", cancelled:"Cancelled"};
  const contextLabels = {date_from:"From",date_to:"To",discipline:"Discipline",campaign:"Campaign",contract_week:"Week",panel_mode:"Mode",panel_discipline:"Discipline",vessel:"Vessel"};
  const form = dialog.querySelector("[data-sn-form]");
  const history = dialog.querySelector("[data-sn-history]");
  const list = dialog.querySelector("[data-sn-list]");
  const message = dialog.querySelector("[data-sn-message]");
  const filter = dialog.querySelector("[data-sn-filter]");
  let section, opener, page = 1, busy = false, today = "", requestId;
  const bars = {};
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function button(text, callback, cls) {
    const node = el("button", text, cls || "sn-button"); node.type = "button";
    node.addEventListener("click", callback); return node;
  }
  function uuid() {
    const b = crypto.getRandomValues(new Uint8Array(16)); b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    const h = Array.from(b, x => x.toString(16).padStart(2,"0")).join("");
    return [h.slice(0,8),h.slice(8,12),h.slice(12,16),h.slice(16,20),h.slice(20)].join("-");
  }
  function dateText(value, time) {
    if (!value) return "No due date";
    return new Date(time ? value : value+"T12:00:00").toLocaleString("en-GB", time ? {dateStyle:"short",timeStyle:"short"} : {dateStyle:"short"});
  }
  async function api(url, data) {
    const response = await fetch(url, {method:data ? "POST":"GET", credentials:"same-origin", cache:"no-store",
      headers:data ? {"Content-Type":"application/json", "X-CSRFToken":form.elements.csrfmiddlewaretoken.value} : {},
      body:data ? JSON.stringify(data) : undefined});
    if (response.redirected || !(response.headers.get("Content-Type") || "").includes("application/json"))
      throw Error("Your session expired or the service is unavailable. Reload the page and sign in again.");
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Unable to complete the request. Please try again.");
    return result;
  }
  async function run(work) {
    if (busy) return;
    busy = true; dialog.setAttribute("aria-busy","true");
    const controls = Array.from(dialog.querySelectorAll("button, select, input, textarea"), n => [n, n.disabled]);
    controls.forEach(([n]) => {n.disabled = true;});
    try { await work(); } catch (error) { message.textContent = error.message; }
    finally { busy = false; dialog.removeAttribute("aria-busy"); controls.forEach(([n, disabled]) => {if(n.isConnected) n.disabled = disabled;}); }
  }
  async function summary() {
    try {
      const data = await api(dialog.dataset.api); today = data.today;
      if (legacyButton) {
        const previous = Object.entries(legacyLabels).filter(([key]) => data.sections[key] && data.sections[key].total);
        legacyButton.hidden = !previous.length;
        const selected = legacySelect.value;
        legacySelect.replaceChildren();
        previous.forEach(([key,label]) => {const option=el("option",label);option.value=key;legacySelect.append(option);});
        if(previous.some(([key])=>key===selected)) legacySelect.value=selected;
      }
      for (const [key, record] of Object.entries(data.sections)) {
        const bar = bars[key]; if (!bar) continue;
        bar.count.textContent = String(record.total);
        bar.count.title = `${record.pending} pending · ${record.total} records`;
        bar.count.setAttribute("aria-label", bar.count.title);
        bar.people.replaceChildren();
        record.people.slice(0,5).forEach(person => {
          const names = person.name.trim().split(/\s+/);
          const initials = (names[0][0] + (names.length > 1 ? names[names.length-1][0] : names[0][1] || "")).toUpperCase();
          const avatar = el("span", initials, "sn-avatar"); avatar.title = person.name; avatar.setAttribute("aria-label",person.name); avatar.tabIndex=0;
          bar.people.append(avatar);
        });
        if(record.people.length>5) {
          const extra=el("span", "+"+(record.people.length-5),"sn-avatar");
          extra.title=record.people.slice(5).map(p=>p.name).join(", ");extra.tabIndex=0;extra.setAttribute("aria-label",extra.title);bar.people.append(extra);
        }
      }
    } catch (_error) { Object.values(bars).forEach(bar => {bar.count.textContent="!";bar.count.title="History unavailable";}); }
  }
  function tab(mode) {
    form.hidden = mode !== "new"; history.hidden = mode !== "history";
    dialog.querySelectorAll("[data-sn-tab]").forEach(n=>n.setAttribute("aria-pressed",String(n.dataset.snTab===mode)));
  }
  function renderNote(note) {
    const article=el("article",undefined,"sn-entry "+note.status);
    const head=el("div",undefined,"sn-entry-head");
    head.append(el("strong",note.author),el("span",statuses[note.status],"sn-badge "+note.status));
    if(note.information_only) head.append(el("span","Information only","sn-badge"));
    article.append(head,el("p",note.body,"sn-body"));
    const meta=el("div",undefined,"sn-entry-meta");
    meta.append(el("span","Date: "+dateText(note.date)),el("span","Created: "+dateText(note.created_at,true)),el("span","Due: "+dateText(note.due_date)));
    article.append(meta);
    if(Object.keys(note.context).length) article.append(el("p",Object.entries(note.context).map(([k,v])=>(contextLabels[k]||k)+": "+v).join(" · "),"sn-context"));
    const actions=el("div",undefined,"sn-status-form"),label=el("label","Status"),select=el("select");
    select.setAttribute("aria-label","Comment status for "+note.author);
    Object.entries(statuses).forEach(([key,value])=>{const opt=el("option",value);opt.value=key;select.append(opt);});
    select.value=note.status;label.append(select);
    actions.append(label,button("Save status",()=>run(async()=>{
      message.textContent="Saving changes…";
      await api(dialog.dataset.statusUrl.replace("/0/","/"+note.id+"/"),{status:select.value,version:note.version});
      await loadHistory(); message.textContent="Status updated. Author, date and time recorded."; await summary();
    })));
    article.append(actions);
    const details=el("details"),events=el("ol");
    details.append(el("summary","Change history · "+note.events.length));
    note.events.forEach(event=>events.append(el("li",`${dateText(event.at,true)} · ${event.actor} · ${event.from ? statuses[event.from]+" → "+statuses[event.to] : "Created as "+statuses[event.to]}`)));
    details.append(events);article.append(details);return article;
  }
  async function loadHistory() {
    const data=await api(dialog.dataset.api+"?"+new URLSearchParams({...scopeParams(),status:filter.value,page}));
    list.replaceChildren();
    data.notes.forEach(note=>list.append(renderNote(note)));
    if(!data.notes.length) list.append(el("p","No records match this filter.","sn-help"));
    // Replace pagination buttons so busy-state restoration cannot overwrite their new state.
    const previous=button("Previous",()=>run(async()=>{page--;await loadHistory();}));previous.dataset.snPrev="";previous.disabled=page<=1;
    const next=button("Next",()=>run(async()=>{page++;await loadHistory();}));next.dataset.snNext="";next.disabled=!data.has_next;
    dialog.querySelector("[data-sn-prev]").replaceWith(previous);dialog.querySelector("[data-sn-next]").replaceWith(next);
    dialog.querySelector("[data-sn-page]").textContent=`Page ${page} · ${data.total} records`;
  }
  function open(key,mode,source) {
    if(busy) return;
    section=key;opener=source;page=1;filter.value="all";message.textContent="";
    const legacy = !panels.has(key);
    legacyLabel.hidden = !legacy;
    dialog.querySelector('[data-sn-tab="new"]').hidden = legacy;
    if(legacy) { mode="history"; legacySelect.value=key; }
    document.getElementById("snTitle").textContent=labels[key];
    form.reset();requestId=uuid();form.elements.due_date.disabled=false;form.elements.due_date.required=true;
    form.elements.date.value=today || new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
    form.elements.date.max=form.elements.date.value;
    tab(mode);dialog.showModal();document.documentElement.classList.add("sn-modal-open");
    if(mode==="history") run(async()=>{message.textContent="Loading records…";await loadHistory();message.textContent="";});
    else form.elements.body.focus();
  }
  panels.forEach((target,key)=>{
    const label=labels[key];
    const bar=el("div",undefined,"sn-bar");bar.setAttribute("aria-label","Comments for "+label);
    const add=button("",()=>open(key,"new",add));
    const icon=el("i",undefined,"bi bi-exclamation-circle-fill");icon.setAttribute("aria-hidden","true");add.prepend(icon);add.title="Add comment";add.setAttribute("aria-label","Add comment · "+label);
    const view=button("History",()=>open(key,"history",view));view.setAttribute("aria-label","View comments · "+label);
    const count=el("span","…","sn-bar-count"),people=el("div",undefined,"sn-people");people.setAttribute("aria-label","People who commented on this panel");
    view.append(count);bar.append(add,view,people);target.append(bar);bars[key]={count,people};
  });
  if(legacyButton) legacyButton.addEventListener("click",()=>{if(legacySelect.value)open(legacySelect.value,"history",legacyButton);});
  legacySelect.addEventListener("change",()=>run(async()=>{section=legacySelect.value;page=1;document.getElementById("snTitle").textContent=labels[section];await loadHistory();}));
  form.elements.information_only.addEventListener("change",()=>{
    form.elements.due_date.disabled=form.elements.information_only.checked;
    form.elements.due_date.required=!form.elements.information_only.checked;
  });
  form.addEventListener("submit",event=>{event.preventDefault();run(async()=>{
    message.textContent="Saving comment…";
    const context=Object.fromEntries(new URLSearchParams(location.search));
    const panelNode=panels.get(section);
    const card=panelNode && panelNode.closest("[data-fab-rundown], [data-fab-skyline]");
    if(card) {
      context.panel_mode=card.dataset.rundownMode || card.dataset.skylineMode || "fabrication";
      const selector=card.querySelector("select");
      context.panel_discipline=card.dataset.rundownDiscipline || (selector && selector.value) || "";
    }
    if(section.startsWith("vessel-")) {
      const vessel=document.querySelector("[data-vt-name]");if(vessel)context.vessel=vessel.textContent;
    }
    await api(dialog.dataset.api,{...scopeParams(),request_id:requestId,date:form.elements.date.value,body:form.elements.body.value,
      due_date:form.elements.information_only.checked ? null : form.elements.due_date.value,information_only:form.elements.information_only.checked,context});
    form.reset();requestId=uuid();tab("history");filter.value="all";page=1;
    await loadHistory();message.textContent="Comment saved under your name.";await summary();
  });});
  dialog.querySelectorAll("[data-sn-tab]").forEach(node=>node.addEventListener("click",()=>{
    if(busy)return;message.textContent="";tab(node.dataset.snTab);
    if(node.dataset.snTab==="history")run(loadHistory);
    else {if(!form.elements.date.value)form.elements.date.value=today;form.elements.due_date.disabled=form.elements.information_only.checked;form.elements.due_date.required=!form.elements.information_only.checked;}
  }));
  filter.addEventListener("change",()=>run(async()=>{page=1;await loadHistory();}));
  dialog.querySelector("[data-sn-refresh]").addEventListener("click",()=>run(async()=>{await loadHistory();message.textContent="";await summary();}));
  dialog.querySelector("[data-sn-close]").addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",event=>{if(busy)event.preventDefault();});
  dialog.addEventListener("close",()=>{document.documentElement.classList.remove("sn-modal-open");if(opener)opener.focus();});
  window.addEventListener("focus",()=>{if(!busy)summary();});
  summary();
}());
