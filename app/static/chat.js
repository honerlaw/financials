(function () {
  const QUICK_ACTIONS = [
    {
      label: 'Spending summary',
      prompt: "Give me a spending summary for the most recent complete calendar month: monthly totals for the last 3 months, top 10 merchants, category breakdown (you infer categories from descriptions), and month-over-month % change."
    },
    {
      label: 'Recurring',
      prompt: "Find my recurring expenses (bills, subscriptions, regular transfers) across the last 6 months. Group into Bills / Subscriptions / Regular Transfers, show typical amount and how many months each appeared, and end with an estimated monthly recurring total."
    },
    {
      label: 'Spending breakdown',
      prompt: "Break down my spending by category for the most recent complete calendar month. Infer categories from descriptions. Show a table sorted by total spent descending, and list any transactions you couldn't confidently categorize."
    },
    {
      label: 'Cross-account',
      prompt: "Show me a cross-account cash flow summary for the most recent complete calendar month: total inflow vs outflow, per-institution net, spend distribution percentages, and a 3-month trend. Call out anything notable."
    },
  ];

  const messagesEl = document.getElementById('messages');
  const chipsEl = document.getElementById('chips');
  const form = document.getElementById('chat-form');
  const input = document.getElementById('chat-input');
  const history = []; // {role, content, tool_calls?, tool_call_id?}
  let busy = false;

  function render() {
    chipsEl.innerHTML = '';
    QUICK_ACTIONS.forEach(({ label, prompt }) => {
      const btn = document.createElement('button');
      btn.className = 'btn btn-outline-secondary chip-btn';
      btn.textContent = label;
      btn.disabled = busy;
      btn.onclick = () => send(prompt);
      chipsEl.appendChild(btn);
    });
  }

  function bubble(cls) {
    const el = document.createElement('div');
    el.className = `msg ${cls}`;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function renderMarkdown(el, text) {
    el.innerHTML = window.marked ? window.marked.parse(text) : text;
  }

  async function send(text) {
    if (busy || !text.trim()) return;
    busy = true;
    render();

    const userBubble = bubble('user');
    userBubble.textContent = text;
    history.push({ role: 'user', content: text });

    const assistantBubble = bubble('assistant');
    let assistantText = '';
    const toolChips = new Map(); // id -> { el, name }
    const pendingToolCalls = []; // captured for history

    try {
      const resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const ev = parseFrame(frame);
          if (!ev) continue;
          handleEvent(ev, assistantBubble, toolChips, pendingToolCalls, (t) => {
            assistantText += t;
            renderMarkdown(assistantBubble, assistantText);
          });
        }
      }
    } catch (err) {
      const errBubble = bubble('error');
      errBubble.textContent = `Connection error: ${err.message}. Click retry to resend.`;
      const retry = document.createElement('button');
      retry.className = 'btn btn-sm btn-outline-danger ms-2';
      retry.textContent = 'Retry';
      retry.onclick = () => { history.pop(); send(text); };
      errBubble.appendChild(retry);
    } finally {
      // Persist the assistant turn in history so subsequent turns include context.
      const assistantMsg = { role: 'assistant' };
      if (assistantText) assistantMsg.content = assistantText;
      if (pendingToolCalls.length) assistantMsg.tool_calls = pendingToolCalls;
      if (assistantText || pendingToolCalls.length) history.push(assistantMsg);
      busy = false;
      render();
    }
  }

  function parseFrame(frame) {
    let event = null;
    let data = '';
    for (const line of frame.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7);
      else if (line.startsWith('data: ')) data += line.slice(6);
    }
    if (!event) return null;
    try { return { event, data: JSON.parse(data) }; }
    catch { return { event, data: {} }; }
  }

  function handleEvent(ev, assistantBubble, toolChips, pendingToolCalls, appendText) {
    if (ev.event === 'text') {
      appendText(ev.data.delta || '');
    } else if (ev.event === 'tool_start') {
      const chip = document.createElement('div');
      chip.className = 'tool-chip';
      chip.textContent = `Calling ${ev.data.name}…`;
      assistantBubble.appendChild(chip);
      toolChips.set(ev.data.id, { el: chip, name: ev.data.name });
      pendingToolCalls.push({
        id: ev.data.id, type: 'function',
        function: { name: ev.data.name, arguments: JSON.stringify(ev.data.args || {}) },
      });
    } else if (ev.event === 'tool_result') {
      const entry = toolChips.get(ev.data.id);
      if (entry) {
        const summary = describeResult(ev.data.result);
        entry.el.innerHTML = `${entry.name} → ${summary} <details><summary>details</summary><pre>${escapeHtml(JSON.stringify(ev.data.result, null, 2))}</pre></details>`;
      }
    } else if (ev.event === 'error') {
      const errChip = document.createElement('div');
      errChip.className = 'msg error';
      errChip.textContent = ev.data.message || 'Unknown error';
      assistantBubble.appendChild(errChip);
    }
    // 'done' ends the stream; loop exits on reader close.
  }

  function describeResult(r) {
    if (!r) return 'no result';
    if (r.error) return `error: ${r.error}`;
    if (Array.isArray(r.rows)) return `${r.count} rows${r.truncated ? ' (truncated)' : ''}`;
    if (Array.isArray(r.groups)) return `${r.groups.length} groups`;
    if (Array.isArray(r.candidates)) return `${r.candidates.length} candidates`;
    if (Array.isArray(r.institutions)) return `${r.institutions.length} institutions`;
    if (r.date) return r.date;
    if (r.earliest || r.latest) return `${r.earliest || '—'} … ${r.latest || '—'}`;
    return 'ok';
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = '';
    send(text);
  });

  render();
})();
