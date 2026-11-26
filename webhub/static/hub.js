const cards = [...document.querySelectorAll("[data-model]")];
const release = document.querySelector("#release");
const notice = document.querySelector("#notice");
const bytes = value => {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let n = 0;
  while (value >= 1024 && n < units.length - 1) { value /= 1024; n++; }
  return `${value.toFixed(n ? 1 : 0)} ${units[n]}`;
};

async function refresh() {
  const response = await fetch("/api/models", {cache: "no-store"});
  if (!response.ok) throw Error(`Status request failed: ${response.status}`);
  const models = await response.json();
  for (const m of models) {
    const card = cards.find(c => c.dataset.model === m.id);
    const text = (field, value) => card.querySelector(`[data-field="${field}"]`).textContent = value;
    text("runtime", m.busy ? `${m.state} · in use` : m.state);
    text("download", m.download);
    text("size", bytes(m.disk_bytes));
    const files = card.querySelector('[data-field="files"]');
    files.replaceChildren(...(m.files.length ? m.files.map(f => `${f.file} · ${bytes(f.bytes)}`) : ["No files yet."]).map(name => {
      const item = document.createElement("li");
      item.textContent = name;
      return item;
    }));
    text("transfer", m.transfers.map(t => `${t.repo}: ${bytes(t.bytes)} received`).join(", "));
    text("error", m.error || "");
    card.querySelector('[data-action="load"]').disabled = ["loaded", "loading"].includes(m.state);
    card.querySelector('[data-action="unload"]').disabled = m.busy || m.state === "unloaded";
  }
  release.disabled = models.some(m => m.busy) || models.every(m => m.state === "unloaded");
}

async function post(path, button) {
  button.disabled = true;
  notice.textContent = "";
  try {
    const result = await fetch(path, {method: "POST"});
    if (!result.ok) throw Error((await result.json()).detail || result.statusText);
    await refresh();
  } catch (e) { notice.textContent = e.message; }
}
for (const card of cards) {
  for (const button of card.querySelectorAll("button"))
    button.onclick = () => post(`/api/models/${card.dataset.model}/${button.dataset.action}`, button);
}
release.onclick = () => post("/api/models/unload", release);
(async function poll() {
  try { await refresh(); }
  catch (e) { notice.textContent = `Cannot refresh model status: ${e.message}`; }
  setTimeout(poll, 2000);
})();
