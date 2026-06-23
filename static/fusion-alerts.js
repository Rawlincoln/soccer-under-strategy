/** Alert setup panel for the Fusion page (Telegram / Discord / WhatsApp / browser). */
const FusionAlerts = (() => {
  const $ = (id) => document.getElementById(id);

  function toast(msg) {
    if (typeof BetAssistant !== "undefined" && BetAssistant.toast) {
      BetAssistant.toast(msg, 4000);
    } else {
      alert(msg);
    }
  }

  function updateStatus(cfg) {
    const el = $("fusionAlertStatus");
    if (!el || !cfg) return;
    const parts = [];
    if (cfg.fusion_alerts_enabled !== false) parts.push("Fusion scans ON");
    if (cfg.telegram_enabled && cfg.telegram_configured) parts.push("Telegram ✓");
    else if (cfg.telegram_enabled) parts.push("Telegram — add chat ID");
    if (cfg.discord_enabled && cfg.discord_configured) parts.push("Discord ✓");
    else if (cfg.discord_enabled) parts.push("Discord — add webhook");
    if (cfg.whatsapp_enabled && cfg.whatsapp_configured) parts.push("WhatsApp ✓");
    else if (cfg.whatsapp_enabled) parts.push("WhatsApp — finish setup");
    if (cfg.browser_alerts !== false) parts.push("Browser ✓");
    const ready = (
      cfg.fusion_alerts_enabled !== false && (
        (cfg.telegram_enabled && cfg.telegram_configured)
        || (cfg.discord_enabled && cfg.discord_configured)
        || (cfg.whatsapp_enabled && cfg.whatsapp_configured)
        || cfg.browser_alerts !== false
      )
    );
    el.textContent = parts.length ? parts.join(" · ") : "Not configured — expand setup below";
    el.className = "fusion-alert-status" + (ready ? " ready" : " warn");
  }

  function applyConfig(cfg) {
    if (!cfg) return;
    if ($("faBrowser")) $("faBrowser").checked = cfg.browser_alerts !== false;
    if ($("faTelegram")) $("faTelegram").checked = !!cfg.telegram_enabled;
    if ($("faDiscord")) $("faDiscord").checked = !!cfg.discord_enabled;
    if ($("faWhatsapp")) $("faWhatsapp").checked = !!cfg.whatsapp_enabled;
    if (cfg.telegram_chat_id && $("faTgChat")) $("faTgChat").value = cfg.telegram_chat_id;
    if (cfg.whatsapp_phone && $("faWaPhone")) $("faWaPhone").value = cfg.whatsapp_phone;
    const tgToken = $("faTgToken");
    if (tgToken) {
      tgToken.placeholder = cfg.telegram_token_set
        ? "Token saved (leave blank to keep)"
        : "Paste bot token from @BotFather";
      if (cfg.telegram_token_set) tgToken.value = "";
    }
    const discord = $("faDiscordUrl");
    if (discord) {
      discord.placeholder = cfg.discord_webhook_set
        ? "Webhook saved (leave blank to keep)"
        : "https://discord.com/api/webhooks/...";
    }
    const waKey = $("faWaKey");
    if (waKey) {
      waKey.placeholder = cfg.whatsapp_apikey_set
        ? "API key saved (leave blank to keep)"
        : "CallMeBot API key";
    }
    if (typeof BetAssistant !== "undefined") {
      BetAssistant.setBrowserAlerts(cfg.browser_alerts !== false);
    }
    updateStatus(cfg);
  }

  function buildSaveBody() {
    const body = {
      fusion_alerts_enabled: true,
      browser_alerts: $("faBrowser")?.checked !== false,
      telegram_enabled: $("faTelegram")?.checked || false,
      discord_enabled: $("faDiscord")?.checked || false,
      whatsapp_enabled: $("faWhatsapp")?.checked || false,
    };
    const token = $("faTgToken")?.value.trim();
    const chat = $("faTgChat")?.value.trim();
    const discord = $("faDiscordUrl")?.value.trim();
    const phone = $("faWaPhone")?.value.trim();
    const waKey = $("faWaKey")?.value.trim();
    if (token) body.telegram_bot_token = token;
    if (chat) body.telegram_chat_id = chat;
    if (discord) body.discord_webhook_url = discord;
    if (phone) body.whatsapp_phone = phone;
    if (waKey) body.whatsapp_apikey = waKey;
    return body;
  }

  async function loadConfig() {
    try {
      const res = await fetch("/api/assistant/config");
      applyConfig(await res.json());
    } catch {
      updateStatus({ fusion_alerts_enabled: true, browser_alerts: true });
    }
  }

  async function saveConfig() {
    const btn = $("faSave");
    if (btn) btn.disabled = true;
    try {
      const res = await fetch("/api/assistant/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildSaveBody()),
      });
      const data = await res.json();
      if (!data.ok) throw new Error("Save failed");
      applyConfig(data.config);
      if (typeof BetAssistant !== "undefined") {
        BetAssistant.setBrowserAlerts(data.config.browser_alerts !== false);
        if (data.config.browser_alerts !== false) {
          await BetAssistant.requestNotifyPermission();
        }
      }
      toast("Alert settings saved");
    } catch (e) {
      toast(e.message || "Could not save settings");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function testAlerts() {
    const btn = $("faTest");
    if (btn) btn.disabled = true;
    try {
      const res = await fetch("/api/assistant/alerts/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildSaveBody()),
      });
      const data = await res.json();
      const ch = data.channels || {};
      const lines = Object.entries(ch).map(([k, v]) => `${k}: ${v.ok ? "OK" : (v.error || "failed")}`);
      if (data.ok) {
        toast(lines.join(" · ") || "Test sent!");
        await saveConfig();
      } else {
        toast(data.error || lines.join(" · ") || "Test failed — check your settings");
      }
    } catch {
      toast("Test request failed — is the server running?");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function discoverChat() {
    const btn = $("faDiscover");
    const token = $("faTgToken")?.value.trim();
    if (btn) btn.disabled = true;
    try {
      const res = await fetch("/api/assistant/telegram/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(token ? { telegram_bot_token: token } : {}),
      });
      const data = await res.json();
      const box = $("faChatPick");
      if (!data.ok || !data.chats?.length) {
        if (box) box.hidden = true;
        toast(data.error || "Message your bot in Telegram first, then try again");
        return;
      }
      if (box) {
        box.hidden = false;
        box.innerHTML = data.chats.map((c) => `
          <button type="button" class="fa-chat-btn" data-chat="${c.chat_id}">
            ${c.name || c.title || c.username || "Chat"} · ID ${c.chat_id}
          </button>
        `).join("");
        box.querySelectorAll(".fa-chat-btn").forEach((b) => {
          b.onclick = () => { if ($("faTgChat")) $("faTgChat").value = b.dataset.chat; };
        });
      }
      if (data.chats.length === 1 && $("faTgChat")) {
        $("faTgChat").value = data.chats[0].chat_id;
      }
      toast(`Found ${data.chats.length} chat(s) — click one, then Save`);
    } catch {
      toast("Could not reach Telegram");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function pollFusionAlerts() {
    try {
      const res = await fetch("/api/assistant");
      const data = await res.json();
      const fusion = (data.new_alerts || []).filter((a) => a.type === "fusion");
      if (fusion.length && typeof BetAssistant !== "undefined") {
        BetAssistant.processAlerts(fusion);
      }
      if (data.config) applyConfig(data.config);
    } catch { /* ignore */ }
  }

  function startPolling(intervalMs) {
    pollFusionAlerts();
    setInterval(pollFusionAlerts, intervalMs || 15000);
  }

  function bind() {
    $("faToggle")?.addEventListener("click", () => {
      const body = $("faBody");
      const open = body?.hidden;
      if (body) body.hidden = !open;
      $("faToggle")?.setAttribute("aria-expanded", open ? "true" : "false");
    });
    $("faSave")?.addEventListener("click", saveConfig);
    $("faTest")?.addEventListener("click", testAlerts);
    $("faDiscover")?.addEventListener("click", discoverChat);
    $("faBrowser")?.addEventListener("change", async () => {
      if ($("faBrowser").checked && typeof BetAssistant !== "undefined") {
        await BetAssistant.requestNotifyPermission();
      }
    });
  }

  function init(intervalMs) {
    bind();
    loadConfig().then(() => {
      if (typeof BetAssistant !== "undefined") {
        BetAssistant.requestNotifyPermission();
      }
      startPolling(intervalMs);
    });
  }

  return { init, loadConfig, saveConfig, testAlerts };
})();