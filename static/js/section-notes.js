(function () {
  "use strict";
  const dialog = document.getElementById("sectionNotesDialog");
  if (!dialog || !dialog.showModal) return;
  const labels = {s00:"Planejamento", s01:"Engenharia", s02:"Suprimentos", s03:"Fabricação", s04:"Logística", s05:"Modelo 3D"};
  const statuses = {pending:"Pendente", resolved:"Sanado", cancelled:"Cancelado"};
  const contextLabels = {date_from:"De",date_to:"Até",discipline:"Disciplina",campaign:"Campanha",contract_week:"Semana"};
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
    if (!value) return "Sem prazo";
    return new Date(time ? value : value+"T12:00:00").toLocaleString("pt-BR", time ? {dateStyle:"short",timeStyle:"short"} : {dateStyle:"short"});
  }
  async function api(url, data) {
    const response = await fetch(url, {method:data ? "POST":"GET", credentials:"same-origin", cache:"no-store",
      headers:data ? {"Content-Type":"application/json", "X-CSRFToken":form.elements.csrfmiddlewaretoken.value} : {},
      body:data ? JSON.stringify(data) : undefined});
    if (response.redirected || !(response.headers.get("Content-Type") || "").includes("application/json"))
      throw Error("Sessão expirada ou serviço indisponível. Recarregue a página e entre novamente.");
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Não foi possível concluir. Tente novamente.");
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
      for (const [key, record] of Object.entries(data.sections)) {
        const bar = bars[key]; if (!bar) continue;
        bar.count.textContent = record.total ? `${record.pending} pendência(s) · ${record.total} registro(s)` : "Nenhum registro";
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
    } catch (_error) { Object.values(bars).forEach(bar => {bar.count.textContent="Histórico indisponível";}); }
  }
  function tab(mode) {
    form.hidden = mode !== "new"; history.hidden = mode !== "history";
    dialog.querySelectorAll("[data-sn-tab]").forEach(n=>n.setAttribute("aria-pressed",String(n.dataset.snTab===mode)));
  }
  function renderNote(note) {
    const article=el("article",undefined,"sn-entry "+note.status);
    const head=el("div",undefined,"sn-entry-head");
    head.append(el("strong",note.author),el("span",statuses[note.status],"sn-badge "+note.status));
    if(note.information_only) head.append(el("span","Somente informação","sn-badge"));
    article.append(head,el("p",note.body,"sn-body"));
    const meta=el("div",undefined,"sn-entry-meta");
    meta.append(el("span","Data: "+dateText(note.date)),el("span","Criado: "+dateText(note.created_at,true)),el("span","Previsão: "+dateText(note.due_date)));
    article.append(meta);
    if(Object.keys(note.context).length) article.append(el("p",Object.entries(note.context).map(([k,v])=>(contextLabels[k]||k)+": "+v).join(" · "),"sn-context"));
    const actions=el("div",undefined,"sn-status-form"),label=el("label","Status"),select=el("select");
    select.setAttribute("aria-label","Status do comentário de "+note.author);
    Object.entries(statuses).forEach(([key,value])=>{const opt=el("option",value);opt.value=key;select.append(opt);});
    select.value=note.status;label.append(select);
    actions.append(label,button("Salvar status",()=>run(async()=>{
      message.textContent="Salvando alteração…";
      await api(dialog.dataset.statusUrl.replace("/0/","/"+note.id+"/"),{status:select.value,version:note.version});
      await loadHistory(); message.textContent="Status atualizado. Autor, data e hora registrados."; await summary();
    })));
    article.append(actions);
    const details=el("details"),events=el("ol");
    details.append(el("summary","Histórico de alterações · "+note.events.length));
    note.events.forEach(event=>events.append(el("li",`${dateText(event.at,true)} · ${event.actor} · ${event.from ? statuses[event.from]+" → "+statuses[event.to] : "Criou o registro como "+statuses[event.to]}`)));
    details.append(events);article.append(details);return article;
  }
  async function loadHistory() {
    const data=await api(dialog.dataset.api+"?"+new URLSearchParams({section,status:filter.value,page}));
    list.replaceChildren();
    data.notes.forEach(note=>list.append(renderNote(note)));
    if(!data.notes.length) list.append(el("p","Nenhum registro para este filtro.","sn-help"));
    // Replace pagination buttons so busy-state restoration cannot overwrite their new state.
    const previous=button("Anterior",()=>run(async()=>{page--;await loadHistory();}));previous.dataset.snPrev="";previous.disabled=page<=1;
    const next=button("Próxima",()=>run(async()=>{page++;await loadHistory();}));next.dataset.snNext="";next.disabled=!data.has_next;
    dialog.querySelector("[data-sn-prev]").replaceWith(previous);dialog.querySelector("[data-sn-next]").replaceWith(next);
    dialog.querySelector("[data-sn-page]").textContent=`Página ${page} · ${data.total} registro(s)`;
  }
  function open(key,mode,source) {
    if(busy) return;
    section=key;opener=source;page=1;filter.value="all";message.textContent="";
    document.getElementById("snTitle").textContent=labels[key];
    form.reset();requestId=uuid();form.elements.due_date.disabled=false;form.elements.due_date.required=true;
    form.elements.date.value=today || new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,10);
    form.elements.date.max=form.elements.date.value;
    tab(mode);dialog.showModal();document.documentElement.classList.add("sn-modal-open");
    if(mode==="history") run(async()=>{message.textContent="Carregando registros…";await loadHistory();message.textContent="";});
    else form.elements.body.focus();
  }
  Object.entries(labels).forEach(([key,label])=>{
    const target=document.getElementById(key);if(!target)return;
    const bar=el("div",undefined,"sn-bar");bar.setAttribute("aria-label","Comentários de "+label);
    const add=button(" Registrar",()=>open(key,"new",add));
    const icon=el("i",undefined,"bi bi-exclamation-circle");icon.setAttribute("aria-hidden","true");add.prepend(icon);add.setAttribute("aria-label","Registrar comentário · "+label);
    const view=button("Histórico",()=>open(key,"history",view));view.setAttribute("aria-label","Ver comentários · "+label);
    const count=el("span","Carregando registros…","sn-bar-count"),people=el("div",undefined,"sn-people");people.setAttribute("aria-label","Pessoas que comentaram nesta seção");
    bar.append(add,view,count,people);target.prepend(bar);bars[key]={count,people};
  });
  form.elements.information_only.addEventListener("change",()=>{
    form.elements.due_date.disabled=form.elements.information_only.checked;
    form.elements.due_date.required=!form.elements.information_only.checked;
  });
  form.addEventListener("submit",event=>{event.preventDefault();run(async()=>{
    message.textContent="Salvando comentário…";
    const context=Object.fromEntries(new URLSearchParams(location.search));
    await api(dialog.dataset.api,{section,request_id:requestId,date:form.elements.date.value,body:form.elements.body.value,
      due_date:form.elements.information_only.checked ? null : form.elements.due_date.value,information_only:form.elements.information_only.checked,context});
    form.reset();requestId=uuid();tab("history");filter.value="all";page=1;
    await loadHistory();message.textContent="Comentário registrado em seu nome.";await summary();
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
