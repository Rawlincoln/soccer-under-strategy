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

  function setFieldLock(input, locked, hintText) {
    if (!input) return;
    input.disabled = !!locked;
    const hintId = `${input.id}-lock`;
    let hint = document.getElementById(hintId);
    if (locked) {
      if (!hint) {
        hint = document.createElement("p");
        hint.id = hintId;
        hint.className = "env-lock-hint";
        input.insertAdjacentElement("afterend", hint);
      }
      hint.textContent = hintText || "Locked — set via Render environment variables (permanent)";
      hint.hidden = false;
    } else if (hint) {
      hint.hidden = true;
    }
  }

  function updateServerBanner(cfg, status) {
    const banner = $("faServerBanner");
    if (!banner) return;
    const st = status || {};
    if (cfg?.server_push_ready && st.scanner_running) {
      const ch = (st.channels_ready || []).join(", ") || "configured";
      banner.hidden = false;
      banner.className = "fusion-server-banner permanent";
      banner.innerHTML = (
        `✅ <strong>24/7 server alerts ACTIVE</strong> — scanning every 30s, pushing via ${ch}. `
        + "Close this tab; alerts still arrive on your phone."
      );
      return;
    }
    if (cfg?.alerts_permanent && !cfg?.server_push_ready) {
      banner.hidden = false;
      banner.className = "fusion-server-banner";
      banner.textContent = "Keys saved in Render env — add your Telegram chat ID (or Discord/WhatsApp) to finish setup.";
      return;
    }
    if (cfg?.needs_chat_id) {
      banner.hidden = false;
      banner.className = "fusion-server-banner";
      banner.innerHTML = (
        "Almost ready — bot token is set but <strong>chat ID is missing</strong>. "
        + "Message your bot → Find chat ID → Save, or set <code>TELEGRAM_CHAT_ID</code> in Render once."
      );
      return;
    }
    if (st.on_render && !cfg?.server_push_ready) {
      banner.hidden = false;
      banner.className = "fusion-server-banner";
      banner.innerHTML = (
        "For alerts that survive redeploys: Render dashboard → Environment → add "
        + "<code>TELEGRAM_BOT_TOKEN</code>, <code>TELEGRAM_CHAT_ID</code> (or Discord/WhatsApp vars). Set once, never re-enter."
      );
      return;
    }
    banner.hidden = true;
  }

  function updateStatus(cfg, status) {
    const el = $("fusionAlertStatus");
    if (!el || !cfg) return;
    const st = status || {};
    const parts = [];
    if (st.scanner_running) parts.push("Server scanner ON");
    if (cfg.fusion_alerts_enabled !== false) parts.push("Fusion alerts ON");
    if (cfg.telegram_enabled && cfg.telegram_configured) parts.push("Telegram ✓");
    else if (cfg.telegram_enabled) parts.push("Telegram — add chat ID");
    if (cfg.discord_enabled && cfg.discord_configured) parts.push("Discord ✓");
    else if (cfg.discord_enabled) parts.push("Discord — add webhook");
    if (cfg.whatsapp_enabled && cfg.whatsapp_configured) parts.push("WhatsApp ✓");
    else if (cfg.whatsapp_enabled) parts.push("WhatsApp — finish setup");
    if (cfg.browser_alerts !== false) parts.push("Browser (tab open only)");

    const serverReady = cfg.server_push_ready && st.scanner_running !== false;
    if (serverReady) {
      el.textContent = `24/7 server push ACTIVE · ${parts.filter((p) => !p.startsWith("Browser")).join(" · ")}`;
      el.className = "fusion-alert-status active-247";
    } else {
      el.textContent = parts.length ? parts.join(" · ") : "Not configured — expand setup below";
      const ready = (
        cfg.fusion_alerts_enabled !== false && (
          (cfg.telegram_enabled && cfg.telegram_configured)
          || (cfg.discord_enabled && cfg.discord_configured)
          || (cfg.whatsapp_enabled && cfg.whatsapp_configured)
        )
      );
      el.className = "fusion-alert-status" + (ready ? " ready" : " warn");
    }
    updateServerBanner(cfg, st);
  }

  function applyConfig(cfg, status) {
    if (!cfg) return;
    const locked = cfg.env_locked || {};
    if ($("faBrowser")) $("faBrowser").checked = cfg.browser_alerts !== false;
    if ($("faTelegram")) $("faTelegram").checked = !!cfg.telegram_enabled;
    if ($("faDiscord")) $("faDiscord").checked = !!cfg.discord_enabled;
    if ($("faWhatsapp")) $("faWhatsapp").checked = !!cfg.whatsapp_enabled;
    if (cfg.telegram_chat_id && $("faTgChat")) $("faTgChat").value = cfg.telegram_chat_id;
    if (cfg.whatsapp_phone && $("faWaPhone")) $("faWaPhone").value = cfg.whatsapp_phone;

    const tgToken = $("faTgToken");
    if (tgToken) {
      tgToken.placeholder = locked.telegram_token
        ? "Token set via Render env (permanent)"
        : (cfg.telegram_token_set ? "Token saved (leave blank to keep)" : "Paste bot token from @BotFather");
      if (cfg.telegram_token_set || locked.telegram_token) tgToken.value = "";
      setFieldLock(tgToken, locked.telegram_token);
    }

    const tgChat = $("faTgChat");
    if (tgChat) {
      setFieldLock(tgChat, locked.telegram_chat, "Chat ID set via Render env (permanent)");
    }

    const discord = $("faDiscordUrl");
    if (discord) {
      discord.placeholder = locked.discord
        ? "Webhook set via Render env (permanent)"
        : (cfg.discord_webhook_set ? "Webhook saved (leave blank to keep)" : "https://discord.com/api/webhooks/...");
      setFieldLock(discord, locked.discord);
    }

    const waPhone = $("faWaPhone");
    if (waPhone) setFieldLock(waPhone, locked.whatsapp_phone);

    const waKey = $("faWaKey");
    if (waKey) {
      waKey.placeholder = locked.whatsapp_apikey
        ? "API key set via Render env (permanent)"
        : (cfg.whatsapp_apikey_set ? "API key saved (leave blank to keep)" : "CallMeBot API key");
      setFieldLock(waKey, locked.whatsapp_apikey);
    }

    if (typeof BetAssistant !== "undefined") {
      BetAssistant.setBrowserAlerts(cfg.browser_alerts !== false);
    }
    updateStatus(cfg, status);
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

  async function fetchAlertStatus() {
    try {
      const res = await fetch("/api/alerts/status");
      return await res.json();
    } catch {
      return null;
    }
  }

  async function loadConfig() {
    try {
      const [cfgRes, status] = await Promise.all([
        fetch("/api/assistant/config"),
        fetchAlertStatus(),
      ]);
      applyConfig(await cfgRes.json(), status);
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
      const status = await fetchAlertStatus();
      applyConfig(data.config, status);
      if (typeof BetAssistant !== "undefined") {
        BetAssistant.setBrowserAlerts(data.config.browser_alerts !== false);
        if (data.config.browser_alerts !== false) {
          await BetAssistant.requestNotifyPermission();
        }
      }
      toast(data.config.server_push_ready ? "Saved — 24/7 server alerts active" : "Alert settings saved");
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
        toast(lines.join(" · ") || "Test sent to your phone!");
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
      const [asstRes, status] = await Promise.all([
        fetch("/api/assistant"),
        fetchAlertStatus(),
      ]);
      const data = await asstRes.json();
      const fusion = (data.new_alerts || []).filter((a) => a.type === "fusion");
      if (fusion.length && typeof BetAssistant !== "undefined") {
        BetAssistant.processAlerts(fusion);
      }
      if (data.config) applyConfig(data.config, status);
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