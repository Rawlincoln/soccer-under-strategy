/**
 * 1xBet opener — uses the real 1xbet.co.ke link so Android opens the installed app.
 * (android-app:// and package= intents redirect to Play Store on many phones.)
 */
(function () {
  const data = window.ONEXBET_OPEN || {};
  const httpsUrl = data.https || "";

  const ua = navigator.userAgent || "";
  const isAndroid = /Android/i.test(ua);
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  const inAppBrowser = /Telegram|WhatsApp|FBAN|FBAV|Instagram|Line\//i.test(ua);

  function $(id) {
    return document.getElementById(id);
  }

  function show(el, on) {
    if (el) el.hidden = !on;
  }

  function openMatch() {
    if (!httpsUrl) return;
    window.location.href = httpsUrl;
  }

  function openInChrome() {
    if (!httpsUrl) return;
    try {
      const u = new URL(httpsUrl);
      const path = `${u.host}${u.pathname}${u.search}`;
      const fallback = encodeURIComponent(window.location.href);
      window.location.href =
        `intent://${path}#Intent;scheme=https;package=com.android.chrome;` +
        `action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;` +
        `S.browser_fallback_url=${fallback};end`;
    } catch {
      window.location.href = window.location.href;
    }
  }

  function init() {
    const hint = $("inapp-hint");
    const settingsHint = $("settings-hint");
    const chromeBtn = $("open-chrome");
    const appBtn = $("open-app");
    const webBtn = $("open-web");

    show(hint, inAppBrowser && isAndroid);
    show(chromeBtn, inAppBrowser && isAndroid);
    show(settingsHint, isAndroid);

    if (chromeBtn) chromeBtn.onclick = (e) => { e.preventDefault(); openInChrome(); };
    if (appBtn) appBtn.onclick = (e) => { e.preventDefault(); openMatch(); };
    if (webBtn) webBtn.onclick = (e) => { e.preventDefault(); openMatch(); };

    if (appBtn && !appBtn.textContent.includes("match")) {
      appBtn.textContent = "Open match in 1xBet app";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();